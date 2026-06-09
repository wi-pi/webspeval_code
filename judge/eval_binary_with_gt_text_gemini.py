"""
Script to evaluate agent actions using ground truth steps and Gemini API.
"""
import argparse
import os
import json
import time
import re
import fcntl
from concurrent.futures import ProcessPoolExecutor, as_completed
from google import genai
from google.genai import types
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
* **Screenshot-Thought Pairing**: Each action has a thought and a screenshot showing the page state AFTER that action was executed. They are provided one after the other in the order of the actions. `Scroll` and `wait` actions do not generate screenshots. So use the next available screenshot to understand the next state. 
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
  "reason": "Detailed explanation of the actions taken by the agent, how they compare to the Ground Truth steps, and a precise reason for the final outcome."
}
```
"""


def create_gemini_client(api_key: str = None, use_vertex: bool = False) -> genai.Client:
    """Create and return a Gemini client
    
    Args:
        api_key: API key for Gemini (required if use_vertex=False)
        use_vertex: If True, use Vertex AI with credentials from .env
        
    Returns:
        genai.Client instance
    """
    if use_vertex:
        vertex_project = os.environ.get("VERTEX_AI_PROJECT_ID")
        vertex_location = os.environ.get("VERTEX_AI_LOCATION", "us-central1")
        
        if not vertex_project:
            raise ValueError("VERTEX_AI_PROJECT_ID not set in environment variables")
        
        print(f"Initializing Gemini client with Vertex AI (project: {vertex_project}, location: {vertex_location})")
        return genai.Client(
            vertexai=True,
            project=vertex_project,
            location=vertex_location
        )
    else:
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not provided or set in environment variables")
        
        print("Initializing Gemini client with API key")
        return genai.Client(api_key=api_key)


def check_for_api_errors(process_dir):
    """Check if the task run has API errors or timeout"""
    log_path = os.path.join(process_dir, 'agent.log')
    #print(log_path)
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


def auto_eval_by_gemini(process_dir, gemini_client, api_model, system_prompt, ground_truth_steps, has_timeout=False, temperature=0.0):
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
        matches = re.search(pattern, task_info,flags=re.DOTALL)
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
    prompt_parts = []
    prompt_text = f"TASK INSTRUCTION:\n{task_content}\n\n"
    prompt_text += f"GROUND TRUTH STEPS:\n"
    for i, step in enumerate(ground_truth_steps, 1):
        prompt_text += f"{i}. {step}\n"
    prompt_text += "\n"
    
    # Add agent actions and screenshots in sequence: Action 1 -> Screenshot 1 -> Action 2 -> Screenshot 2...
    for action in agent_actions:
        # Add action text
        action_text = f"--- Iteration {action['iteration']} ---\n"
        action_text += f"AGENT TEXT RESPONSE:\n{action['response']}\n\n"
        prompt_parts.append(types.Part.from_text(text=action_text))
        
        # Add screenshot immediately after the action
        if action['screenshot_path'] and os.path.exists(action['screenshot_path']):
            try:
                with open(action['screenshot_path'], "rb") as image_file:
                    image_data = image_file.read()
            except OSError:
                image_data = None
            if image_data is not None:
                prompt_parts.append(types.Part.from_text(text="VISUAL EVIDENCE:\n"))
                prompt_parts.append(
                    types.Part.from_bytes(
                        data=image_data,
                        mime_type="image/png"
                    )
                )
                prompt_parts.append(types.Part.from_text(text="\n\n"))
            else:
                prompt_parts.append(types.Part.from_text(text="VISUAL EVIDENCE: Failed to read screenshot\n\n"))
        else:
            prompt_parts.append(types.Part.from_text(text="VISUAL EVIDENCE: Not available\n\n"))

    # Add final answer
    if answer_content:
        final_answer_text = f"---\n##AGENT's FINAL ANSWER:\n{answer_content}\n\n"
    else:
        final_answer_text = f"---\n##AGENT's FINAL ANSWER: No answer provided (task timed out)\n\n"
    
    prompt_parts.append(types.Part.from_text(text=final_answer_text))
    prompt_parts.insert(0,types.Part.from_text(text=prompt_text))
    prompt_parts.append(types.Part.from_text(text="\nYour verdict:\n"))
    
    contents = [types.Content(role="user", parts=prompt_parts)]
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print('Calling Gemini API...')
            if '3-pro' in api_model or '3.1-pro' in api_model:
                thinking_config = types.ThinkingConfig(thinking_level="high")
            else:
                thinking_config = types.ThinkingConfig(thinking_budget=-1)
            response = gemini_client.models.generate_content(
                model=api_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    system_instruction=[types.Part.from_text(text=system_prompt)],
                    max_output_tokens=50000,
                    thinking_config=thinking_config,
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "result": {
                                "type": "string",
                                "enum": ["CORRECT", "INCORRECT"]
                            },
                            "reason": {
                                "type": "string",
                                "description": "Detailed explanation of the evaluation result"
                            }
                        },
                        "required": ["result", "reason"]
                    }
                )
            )
            
            print('API call complete')
            break
            
        except Exception as e:
            print(f"Error on attempt {attempt + 1}: {e}")
            error_msg = str(e).lower()
            if "resource" in error_msg or "quota" in error_msg or "rate" in error_msg:
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
    
    gemini_response_text = response.text.strip() if response.text else "No response generated"
    print("Gemini response:")
    print(gemini_response_text)

    try:
        eval_result = json.loads(gemini_response_text)
        raw_result = eval_result.get('result', '')
        result_value = str(raw_result).upper()
        reason_value = eval_result.get('reason', '')

        # Validate result
        if result_value not in ['CORRECT', 'INCORRECT']:
            print(f"Error: Unexpected result value {raw_result!r}; not coercing. Skipping task.")
            return None, None

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
    temperature: float,
    use_vertex: bool = False,
):
    """
    Worker-safe per-task evaluation.
    Returns:
      (task_id_agent_run_name, task_result_dict_or_none, api_error_entry_or_none)
    """

    # The run_json_file may point to either:
    #   - the task dir directly (e.g. .../rq4_evaluation/taskIKEA_task-158)
    #   - the agent run parent dir (older format, suffix `task{task_id}` or `{task_id}`)
    if os.path.isfile(os.path.join(result_dir, "agent.log")):
        task_dir_path = result_dir
    else:
        task_dir_path = os.path.join(result_dir, f"task{task_id}")
        if not os.path.exists(task_dir_path):
            task_dir_path = os.path.join(result_dir, f"{task_id}")

    print(f"Task directory path: {task_dir_path}")
    # Check for API errors first (and timeout flag)
    api_error, has_timeout = check_for_api_errors(task_dir_path)
    if api_error:
        return task_id_agent_run_name, None, {
            'task_id_agent_run_name': task_id_agent_run_name,
            'error': api_error
        }

    # Create a client inside the worker process
    if use_vertex:
        try:
            client = create_gemini_client(use_vertex=True)
        except ValueError as e:
            return task_id_agent_run_name, None, {
                'task_id_agent_run_name': task_id_agent_run_name,
                'error': f'VERTEX_AI_CONFIG_ERROR: {str(e)}'
            }
    else:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            # Treat missing key as an API error so it's tracked in stats_output
            return task_id_agent_run_name, None, {
                'task_id_agent_run_name': task_id_agent_run_name,
                'error': 'GEMINI_API_KEY_NOT_SET'
            }
        client = create_gemini_client(api_key=api_key, use_vertex=False)

    result_value, reason_value = auto_eval_by_gemini(
        task_dir_path,
        client,
        api_model,
        system_prompt,
        ground_truth_steps,
        has_timeout,
        temperature,
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
    parser.add_argument("--api_model", default="gemini-2.5-pro", type=str)
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
    parser.add_argument("--temperature", type=float, default=0.0, help="Temperature for the Gemini API")
    parser.add_argument("--use_vertex", action="store_true", help="Use Vertex AI instead of Gemini API (loads credentials from .env)")
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

    # Validate credentials based on use_vertex flag
    if args.use_vertex:
        vertex_project = os.environ.get("VERTEX_AI_PROJECT_ID")
        if not vertex_project:
            raise ValueError("Please provide VERTEX_AI_PROJECT_ID environment variable for Vertex AI")
        print(f"Using Vertex AI with project: {vertex_project}")
    else:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Please provide GEMINI_API_KEY environment variable")
        print("Using Gemini API with API key")

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
                    args.temperature,
                    args.use_vertex,  # Pass use_vertex flag
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
            'tasks_failed_to_evaluate': tasks_failed_to_evaluate
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
