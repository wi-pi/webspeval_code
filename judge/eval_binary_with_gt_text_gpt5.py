"""
Script to evaluate agent actions using ground truth steps and GPT-5 API via Azure OpenAI.
"""
import argparse
import os
import json
import time
import re
import base64
import fcntl
from concurrent.futures import ProcessPoolExecutor, as_completed
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT_WITH_GT = """# ROLE: WebPrivSecEvaluator Bot

## PRIMARY GOAL
You are an expert evaluator tasked with analyzing the performance of a browser-automation agent (web agent). Your objective is to determine if the agent successfully completed a specific web privacy or security task based on the provided textual and visual evidence, compared against the Ground Truth steps.

---

## INPUT DATA
For each evaluation instance, you will receive:

1.  **Task Query**: The natural language instruction given to the agent.
2.  **Ground Truth Steps**: The expected ideal sequence of actions.
3.  **Result Response**: The agent's textual log describing its thought process and actions.
4.  **Result Screenshots**: A sequence of images corresponding to the agent's actions.

### Crucial Evidence Guidelines
* **Screenshot Trust**: **TRUST THE SCREENSHOTS OVER THE TEXT LOG.** The visual evidence is the ground truth for what actually happened on the page.
* **Screenshot-Thought Pairing**: Each action has a thought and a screenshot showing the page state AFTER that action was executed. They are provided one after the other in the order of the actions. Scroll and wait actions do not generate screenshots. So use the next available screenshot to understand the next state. 
* **Element Identification**: Valid element IDs are typically two-digit numbers. Be vigilant for hallucinations where the model cites implausible element IDs (e.g., [1078], [678]).
* **Ground Truth Usage**: Use the Ground Truth steps as a guide for the *correct solution*. It is possible that the agent does not follow the exact steps but still achieves the correct final outcome. So use the ground truth to understand what are a set of possible actions that are needed to achieve the goal and use that understanding to evaluate the agent's actions and whether they are correct or not.

### Agent Action Space
 The agent can perform the following actions. The final action is always an `ANSWER` acknowledging completion.
`Click`, `Type`, `Scroll`, `Scroll_to_end`, `Scroll_within_popup`, `Switch_tab`, `Wait`, `GoBack`, `Google`, `ANSWER`, `Hover'

---

## CORE EVALUATION LOGIC
1.  **Strict Evidence Adherence**: Do not assume actions were taken unless visible in screenshots or explicitly stated in the log (and supported by context).
2.  **Step Comparison**: Compare the agent's actions against Ground Truth steps to identify missing, redundant, or incorrect actions. Use the ground truth as a reference for the set of possible actions for achieving the goal. Agent can deviate but still achieve the goal. So check the final outcome based on the agent actions while using the ground truth solely as a reference.
3.  **Final State Verification**: Ensure all changes are finalized (e.g., 'Save Preferences' button was actually clicked).

---

## DETERMINING THE RESULT

### General Observations & Edge Cases
Before categorizing the result, consider these specific nuances:

* **Data Request Tasks**: If the agent is unable to successfully complete a data request (e.g., recently requested data so optional not available currently), check the final `ANSWER` and the thoughts of the agent. If the agent correctly identifies the limitation and understands the task intent, this may still be considered valid depending on the context.
* **Element IDs (Click Actions)**: Valid element IDs are typically double-digit numbers. Be vigilant for hallucinations where the model cites implausible element IDs (e.g., `[1078]`, `[678]`). If the agent clicks a non-existent high-number ID, that specific action is mistake from the agent and can impact the overall outcome of the task.
* **"Already Done" States**: In some cases, the requested privacy or security setting may already be active. If the agent correctly identifies that the task is already completed and terminates without changing anything, this is a **CORRECT** result.
* **Toggle States**: Ensure to compare the state of elements like toggles with the desired state from the task instruction very carefully, as these elements form a major part of the tasks you will get.

### 1. CORRECT
The agent executed necessary steps and the final state reflects the desired outcome (matches the expected outcome from Ground Truth).

### 2. INCORRECT
The agent failed to achieve the goal due to any reason (navigation errors, incomplete steps, hallucinated actions, semantic reversals, or post-completion destructive actions).

---

## REASONING GUIDELINES
When writing the `reason` field, you must adhere to the following structure:
1.  **Summary vs. Expected**: Summarize the actual actions taken by the agent and directly compare them with the expected outcome (Ground Truth).
2.  **Why It Failed**: Clearly explain the specific reason(s) why the task was not completed successfully.
3.  **Destructive Action Check**: You must explicitly mention if the agent attempted any destructive or irrelevant high-risk actions.
    * *Examples of destructive actions include:* Deleting accounts, creating new affiliations/subscriptions, or interacting with unrelated external websites.
---

## REQUIRED OUTPUT FORMAT
Provide your evaluation in the following JSON format:

```json
{
  "result": "CORRECT", // or "INCORRECT"
  "reason": "Detailed explanation of the actions taken by the agent, how they compare to the Ground Truth steps, and the reason for the final outcome."
}
```
"""


def create_azure_openai_client() -> AzureOpenAI:
    """Create and return an Azure OpenAI client"""
    return AzureOpenAI(
        api_key=os.environ.get("AZURE_OPENAI_KEY"),
        api_version="2024-12-01-preview",
        azure_endpoint=os.environ.get("ENDPOINT_URL")
    )


def encode_image_base64(image_path: str) -> str:
    """Encode image to base64 string"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def check_for_api_errors(process_dir):
    """Check if the task run has API errors or timeout"""
    log_path = os.path.join(process_dir, 'agent.log')
    try:
        with open(log_path, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        return 'LOG_NOT_FOUND', False
    
    # Check for timeout (not an API error, but a completion indicator)
    has_timeout = "Task execution time limit (180s) exceeded" in content
    
    api_error_message= "API call error"
    if api_error_message in content:
        return api_error_message, has_timeout
    
    
    return None, has_timeout


def auto_eval_by_gpt5(process_dir, openai_client, api_model, system_prompt, ground_truth_steps, has_timeout=False, verbosity="medium", reasoning_effort="medium"):
    print(f'--------------------- {process_dir} ---------------------')
    res_files = sorted(os.listdir(process_dir))
    
    with open(os.path.join(process_dir, 'interact_messages.json')) as fr:
        it_messages = json.load(fr)
    
    if len(it_messages) == 1:
        print('No answer found - only system messages')
        print()
        return None, None
    
    # Extract task instruction
    try:
        print(it_messages[1])
        task_info = it_messages[1]["content"]
        if type(task_info) == list:
            task_info = task_info[0]["text"] if isinstance(task_info[0], dict) else task_info[0]
        assert 'Now given a task' in task_info
        pattern = r"Now given a task:(.+?)Please interact with"
        matches = re.search(pattern, task_info, flags=re.DOTALL)
        task_content = matches.group(1).strip()
        print(f"Task: {task_content}")
    except Exception as e:
        print(f"Error parsing task instruction info: {e}")
        print()
        return None, None
    

    # Extract answer content (if exists - may not exist for timeout/error cases)
    try:
        answer_content = it_messages[-1]["content"]
        if has_timeout:
            answer_content = None
        if isinstance(answer_content, list):
            answer_content = answer_content[0]
        
    except Exception as e:
        print(f"Answer: No answer found - {e}")
    
    # Continue with evaluation even if no answer was provided
    
    # Build mapping of screenshots
    screenshot_map = {}
    pattern_png = r'screenshot(\d+)\.png'
    pattern_fail_png = r'screenshot_fail(\d+)\.png'
    
    for filename in res_files:
        match_normal = re.search(pattern_png, filename)
        match_fail = re.search(pattern_fail_png, filename)
        
        if match_normal:
            screenshot_iteration = int(match_normal.group(1))
            screenshot_map[screenshot_iteration] = os.path.join(process_dir, filename)
        elif match_fail:
            screenshot_iteration = int(match_fail.group(1))
            screenshot_map[screenshot_iteration] = os.path.join(process_dir, filename)
    
    if len(screenshot_map) == 0:
        print('No images found')
        print()
        return None, None
    
    # Load thoughts.json for agent actions
    thoughts_path = os.path.join(process_dir, 'thoughts.json')
    if not os.path.exists(thoughts_path):
        print('thoughts.json not found')
        print()
        return None, None

    with open(thoughts_path) as fr:
        thoughts_data = json.load(fr)

    if not thoughts_data:
        print('No thoughts found')
        print()
        return None, None

    # Extract agent responses and pair with screenshots
    agent_actions = []
    total_thoughts = len(thoughts_data)

    for idx, message in enumerate(thoughts_data):
        iteration_no = message['iteration']
        next_iteration_num = thoughts_data[idx + 1]['iteration'] if idx + 1 < total_thoughts else -1
        agent_response = f"Thought: {message['thought']}\nAction: {message['action']}"
        action_dict = {'iteration': idx + 1, 'response': agent_response}

        if next_iteration_num == iteration_no:
            action_dict['screenshot_path'] = None
        else:
            action_dict['screenshot_path'] = screenshot_map.get(iteration_no, None)

        agent_actions.append(action_dict)
    
    if not agent_actions:
        print('No agent actions found')
        print()
        return None, None
    
    # Build the formatted prompt with task, ground truth, and agent actions
    prompt_text = f"TASK INSTRUCTION:\n{task_content}\n\n"
    prompt_text += f"GROUND TRUTH STEPS:\n"
    for i, step in enumerate(ground_truth_steps, 1):
        prompt_text += f"{i}. {step}\n"
    prompt_text += "\n"
    
    # Build content array for GPT-5 with text and images
    content_parts = []
    content_parts.append({"type": "text", "text": prompt_text})
    
    # Add agent actions and screenshots in sequence
    for action in agent_actions:
        # Add action text
        action_text = f"--- Iteration {action['iteration']} ---\n"
        action_text += f"AGENT TEXT RESPONSE:\n{action['response']}\n\n"
        content_parts.append({"type": "text", "text": action_text})
        
        # Add screenshot immediately after the action
        if action['screenshot_path'] and os.path.exists(action['screenshot_path']):
            content_parts.append({"type": "text", "text": "VISUAL EVIDENCE:\n"})
            
            # Encode image to base64 for GPT-5
            base64_image = encode_image_base64(action['screenshot_path'])
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{base64_image}"
                }
            })
            
            content_parts.append({"type": "text", "text": "\n\n"})
        else:
            content_parts.append({"type": "text", "text": "VISUAL EVIDENCE: Not available\n\n"})

    # Add final answer
    if answer_content:
        final_answer_text = f"---\n##AGENT's FINAL ANSWER:\n{answer_content}\n\n"
    else:
        final_answer_text = f"---\n##AGENT's FINAL ANSWER: No answer provided (task timed out)\n\n"
    
    content_parts.append({"type": "text", "text": final_answer_text})
    content_parts.append({"type": "text", "text": "\nYour verdict:\n"})
    
    # Build messages array for GPT-5
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content_parts}
    ]
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print('Calling GPT-5 API via Azure OpenAI...')
            
            response = openai_client.chat.completions.create(
                model=api_model,
                messages=messages,
                verbosity=verbosity,
                reasoning_effort=reasoning_effort,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "EvaluationResponse",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "result": {
                                    "type": "string",
                                    "description": "The evaluation result indicating whether the agent completed the task correctly",
                                    "enum": ["CORRECT", "INCORRECT"]
                                },
                                "reason": {
                                    "type": "string",
                                    "description": "Detailed explanation of the evaluation result, comparing actual actions with expected outcome and including any destructive actions performed by the agent."
                                }
                            },
                            "required": ["result", "reason"],
                            "additionalProperties": False
                        }
                    }
                },
                stream=False
            )
            
            print('API call complete')
            break
            
        except Exception as e:
            print(f"Error on attempt {attempt + 1}: {e}")
            error_msg = str(e).lower()
            if "rate" in error_msg or "quota" in error_msg or "limit" in error_msg:
                if attempt < max_retries - 1:
                    delay = 10 * (2 ** attempt)
                    print(f"Rate limit hit, retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                else:
                    print("Rate limit exceeded after all retries")
                    return None, None
            elif "invalid" in error_msg:
                print("Invalid request - exiting")
                exit(0)
            else:
                if attempt < max_retries - 1:
                    time.sleep(10)
                    continue
                else:
                    print("Max retries exceeded")
                    return None, None
    
    gpt_response_text = response.choices[0].message.content.strip() if response.choices[0].message.content else "No response generated"
    print("GPT-5 response:")
    print(gpt_response_text)

    try:
        eval_result = json.loads(gpt_response_text)
        result_value = eval_result.get('result', '').upper()
        reason_value = eval_result.get('reason', '')
        
        # Validate result
        if result_value not in ['CORRECT', 'INCORRECT']:
            print(f"Warning: Invalid result value: {result_value}. Defaulting to INCORRECT")
            result_value = 'INCORRECT'
        
        print('Auto_eval_res:', result_value)
        print('Auto_eval_reason:', reason_value)

        return result_value, reason_value
        
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON response: {e}")
        return None, None


def _evaluate_single_task(
    task_id: str,
    result_dir: str,
    api_model: str,
    system_prompt: str,
    task_id_agent_run_name: str,
    ground_truth_steps,
    output_path: str,
    verbosity: str,
    reasoning_effort: str,
):
    """
    Worker-safe per-task evaluation.
    Returns:
      (task_id_agent_run_name, task_result_dict_or_none, api_error_entry_or_none)
    """
    task_dir_path = os.path.join(result_dir, f"task{task_id}")

    # Check for API errors first (and timeout flag)
    api_error, has_timeout = check_for_api_errors(task_dir_path)
    if api_error:
        return task_id_agent_run_name, None, {
            'task_id_agent_run_name': task_id_agent_run_name,
            'error': api_error
        }

    # Create a client inside the worker process
    api_key = os.environ.get("AZURE_OPENAI_KEY")
    endpoint = os.environ.get("ENDPOINT_URL")
    if not api_key or not endpoint:
        # Treat missing key as an API error so it's tracked in stats_output
        return task_id_agent_run_name, None, {
            'task_id_agent_run_name': task_id_agent_run_name,
            'error': 'AZURE_OPENAI_CREDENTIALS_NOT_SET'
        }

    client = create_azure_openai_client()

    result_value, reason_value = auto_eval_by_gpt5(
        task_dir_path,
        client,
        api_model,
        system_prompt,
        ground_truth_steps,
        has_timeout,
        verbosity,
        reasoning_effort,
    )

    if result_value is None:
        return task_id_agent_run_name, None, None

    # Build result dict for this task
    result_dict = {
        'result': result_value,
        'reason': reason_value,
        'timeout': has_timeout,
        'agent_api_error': api_error,
    }

    # Persist this single task's result inside the worker with file locking
    # to prevent concurrent workers from clobbering each other's writes.
    lock_path = output_path + ".lock"
    try:
        with open(lock_path, 'w') as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            existing = {}
            if os.path.exists(output_path):
                with open(output_path, 'r') as fr:
                    try:
                        existing = json.load(fr)
                    except json.JSONDecodeError:
                        existing = {}
            existing[task_id_agent_run_name] = result_dict
            with open(output_path, 'w') as fw:
                json.dump(existing, fw, indent=2)
    except Exception as e:
        print(f"Warning: failed to persist result for {task_id_agent_run_name} inside worker: {e}")

    return task_id_agent_run_name, result_dict, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run_json_file', type=str, default='tuning_set_run_args.json')
    parser.add_argument("--api_model", default="gpt-5.2", type=str)
    parser.add_argument("--experiment_dir", type=str, default=None,
                        help=(
                            "Directory for all per-run outputs. When set, "
                            "output_path defaults to <exp>/outputs.json and "
                            "stats_output_path to <exp>/stats.json (unless "
                            "overridden). Rerunning skips tasks already in "
                            "outputs.json so it continues incrementally."
                        ))
    parser.add_argument("--output_path", type=str, default=None)
    parser.add_argument("--stats_output_path", type=str, default=None)
    parser.add_argument("--n-proc", type=int, default=5, help="Number of worker processes for parallel evaluation")
    parser.add_argument("--ground_truth_file", type=str, required=True,
                        help='Path to ground truth JSON file')
    parser.add_argument("--task_ids_file", type=str, default='with_navigation_task_ids.json')
    parser.add_argument("--verbosity", type=str, default="medium", help="Verbosity for the GPT-5 API")
    parser.add_argument("--reasoning_effort", type=str, default="medium", help="Reasoning effort for the GPT-5 API")

    args = parser.parse_args()

    # Resolve defaults based on --experiment_dir (or fall back to legacy)
    if args.experiment_dir:
        os.makedirs(args.experiment_dir, exist_ok=True)
        if not args.output_path:
            args.output_path = os.path.join(args.experiment_dir, "outputs.json")
        if not args.stats_output_path:
            args.stats_output_path = os.path.join(args.experiment_dir, "stats.json")
    if not args.output_path:
        args.output_path = "outputs_with_gt.json"
    if not args.stats_output_path:
        args.stats_output_path = "evaluation_stats_with_gt.json"

    api_key = os.environ.get("AZURE_OPENAI_KEY")
    endpoint = os.environ.get("ENDPOINT_URL")
    if not api_key or not endpoint:
        raise ValueError("Please provide AZURE_OPENAI_KEY and ENDPOINT_URL environment variables")

    # Load ground truth
    with open(args.ground_truth_file, 'r') as f:
        ground_truth_data = json.load(f)

    # Load task ids
    with open(args.task_ids_file, 'r') as f:
        task_ids = json.load(f)

    # Load output file if it exists
    if os.path.exists(args.output_path):
        with open(args.output_path, 'r') as f:
            task_res = json.load(f)
        already_evaluated_task_ids = list(task_res.keys())
    else:
        task_res = {}
        already_evaluated_task_ids = []

    # Filter tasks to evaluate
    # Load the run_json_file 
    with open(args.run_json_file, 'r') as f:
        run_json_data = json.load(f)
    task_dirs = list(run_json_data.keys())
    print(f'Number of tasks to evaluate: {len(task_dirs)}')

    ## load the output_path file if it exists
    if os.path.exists(args.output_path):
        with open(args.output_path, 'r') as f:
            task_res = json.load(f)
        already_evaluated_task_ids = list(task_res.keys())
    else:
        task_res = {}
        already_evaluated_task_ids = []
    print(f'Number of tasks already evaluated: {len(already_evaluated_task_ids)}')

    ## filter the task_dirs to only include tasks that are not already evaluated
    task_dirs = [task_dir for task_dir in task_dirs if task_dir not in already_evaluated_task_ids]
    print(f'Number of tasks to evaluate: {len(task_dirs)}')

    api_error_tasks = []
    failed_to_evaluate_tasks = []
    # Parallel evaluation across tasks
    if task_dirs:
        n_proc = max(1, int(args.n_proc))
        print(f'Running evaluation with n_proc={n_proc}')

        with ProcessPoolExecutor(max_workers=n_proc) as executor:
            futures = []
            future_to_id = {}
            for task_id_and_agent_run_name in task_dirs:
                task_id = task_id_and_agent_run_name.split("%%")[0]
                ground_truth_steps = ground_truth_data.get(task_id, [])
                if not ground_truth_steps:
                    ground_truth_steps = ["No ground truth available"]

                fut = executor.submit(
                    _evaluate_single_task,
                    task_id,  # task_id
                    run_json_data[task_id_and_agent_run_name],  # result_dir
                    args.api_model,
                    SYSTEM_PROMPT_WITH_GT,
                    task_id_and_agent_run_name,
                    ground_truth_steps,
                    args.output_path,
                    args.verbosity,
                    args.reasoning_effort,
                )
                futures.append(fut)
                future_to_id[fut] = task_id_and_agent_run_name

            for fut in as_completed(futures):
                task_id_agent_run_name = future_to_id.get(fut, 'UNKNOWN')
                try:
                    task_id_agent_run_name, result_dict, api_error_entry = fut.result()
                except Exception as e:
                    # Catch any worker crash and record as API error-like entry
                    api_error_tasks.append({
                        'task_id_agent_run_name': task_id_agent_run_name,
                        'error': f'WORKER_EXCEPTION: {e}'
                    })
                    continue

                if api_error_entry:
                    api_error_tasks.append(api_error_entry)
                    continue

                if result_dict is None:
                    # Worker couldn't evaluate (e.g., malformed output). Skip.
                    failed_to_evaluate_tasks.append(
                        {'task_id_agent_run_name': task_id_agent_run_name, 'error': 'FAILED_TO_EVALUATE'}
                    )
                    continue

                # Only update in-memory aggregate; per-task persistence is done inside the worker
                task_res[task_id_agent_run_name] = result_dict

    # Final bulk write of all results as a safety net
    with open(args.output_path, 'w') as fw:
        json.dump(task_res, fw, indent=2)
    
    print(f'\nEvaluation completed successfully')
    print(f'Output file: {args.output_path}')
    
    # Compute statistics
    tasks_evaluated = len(task_res)
    agent_api_error_count = len(api_error_tasks)
    tasks_failed_to_evaluate = len(failed_to_evaluate_tasks)
    tasks_attempted = tasks_evaluated + agent_api_error_count + tasks_failed_to_evaluate
    
    if tasks_evaluated > 0:
        print(f'\n=== Evaluation Results (for {tasks_evaluated} evaluated tasks) ===')
        correct_task_count = len([task for task in task_res if task_res[task]['result'] == 'CORRECT'])
        incorrect_task_count = tasks_evaluated - correct_task_count        
        print(f'CORRECT: {correct_task_count} ({correct_task_count / tasks_evaluated * 100:.2f}%)')
        print(f'INCORRECT: {incorrect_task_count} ({incorrect_task_count / tasks_evaluated * 100:.2f}%)')

        # Timeout breakdown
        timeout_count = len([task for task in task_res if task_res[task].get('timeout', False)])
        print(f'Tasks with timeout: {timeout_count} ({timeout_count / tasks_evaluated * 100:.2f}%)')

        # API error breakdown (these tasks were not evaluated and are tracked separately)
        if tasks_attempted > 0:
            print(f'Tasks with Agent API errors: {agent_api_error_count} ({agent_api_error_count / tasks_attempted * 100:.2f}% of attempted)')
        else:
            print(f'Tasks with Agent API errors: {agent_api_error_count}')
        
        # Save statistics to JSON file
        stats_output = {
            'tasks_evaluated': tasks_evaluated,
            'correct': correct_task_count,
            'incorrect': incorrect_task_count,
            'tasks_with_timeout': timeout_count,
            'tasks_with_agent_api_errors': agent_api_error_count,
            'agent_api_error_tasks': api_error_tasks,
            'tasks_failed_to_evaluate': failed_to_evaluate_tasks
        }
        
        with open(args.stats_output_path, 'w') as f:
            json.dump(stats_output, f, indent=2)
        print(f'\nStatistics saved to: {args.stats_output_path}')
    
    # Print API errors at the end
    if api_error_tasks:
        print(f'\n=== Tasks with API Errors ({len(api_error_tasks)}) ===')
        for error_task in api_error_tasks:
            task_identifier = error_task.get('task_id_agent_run_name') or error_task.get('task_id')
            print(f"Task {task_identifier}: {error_task['error']}")
  
if __name__ == '__main__':
    main()
