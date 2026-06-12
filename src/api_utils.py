"""
API utility functions for different model providers (GPT, Claude, Gemini).
Handles message formatting and API calls for each provider.
"""

import logging
import time


def format_msg_claude(it, init_msg, pdf_obs, warn_obs, web_img_b64, web_text, tabs_info=None):
    """Format messages for Claude API with vision support and tab information."""
    # Add tab information to the message
    tabs_text = ""
    if tabs_info:
        tabs_text = "\n\nOpen Tabs:\n"
        for handle, info in tabs_info.items():
            current_indicator = " (CURRENT)" if info['is_current'] else ""
            tabs_text += f"- {info['title']}: {info['url']}{current_indicator}\n"
    
    if it == 1:
        init_msg += f"{tabs_text}\nI've provided the tag name of each element and the text it contains (if text exists). Note that <textarea> or <input> may be textbox, but not exactly. Please focus more on the screenshot and then refer to the textual information.\n{web_text}"
        init_msg_format = {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': init_msg},
                {
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': 'image/png',
                        'data': web_img_b64,
                    },
                }
            ]
        }
        return init_msg_format
    else:
        if not pdf_obs:
            curr_msg = {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': f"Observation:{warn_obs} please analyze the attached screenshot and give the Thought and Action. I've provided the tag name of each element and the text it contains (if text exists). Note that <textarea> or <input> may be textbox, but not exactly. Please focus more on the screenshot and then refer to the textual information.\n{web_text}{tabs_text}"},
                    {
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'media_type': 'image/png',
                            'data': web_img_b64,
                        },
                    }
                ]
            }
        else:
            curr_msg = {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': f"Observation: {pdf_obs} Please analyze the response given by Assistant, then consider whether to continue iterating or not. The screenshot of the current page is also attached, give the Thought and Action. I've provided the tag name of each element and the text it contains (if text exists). Note that <textarea> or <input> may be textbox, but not exactly. Please focus more on the screenshot and then refer to the textual information.\n{web_text}{tabs_text}"},
                    {
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'media_type': 'image/png',
                            'data': web_img_b64,
                        },
                    }
                ]
            }
        return curr_msg  


def format_msg_gpt5(it, init_msg, pdf_obs, warn_obs, web_img_b64, web_text, tabs_info=None):
    """Format messages for GPT API with vision support and tab information."""
    # Add tab information to the message
    tabs_text = ""
    if tabs_info:
        tabs_text = "\n\nOpen Tabs:\n"
        for handle, info in tabs_info.items():
            current_indicator = " (CURRENT)" if info['is_current'] else ""
            tabs_text += f"- {info['title']}: {info['url']}{current_indicator}\n"
    
    if it == 1:
        init_msg += f"{tabs_text}\nI've provided the tag name of each element and the text it contains (if text exists). Note that <textarea> or <input> may be textbox, but not exactly. Please focus more on the screenshot and then refer to the textual information.\n{web_text}"
        init_msg_format = {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': init_msg},
            ]
        }
        init_msg_format['content'].append({"type": "image_url",
                                           "image_url": {"url": f"data:image/png;base64,{web_img_b64}"}})
        return init_msg_format
    else:
        if not pdf_obs:
            curr_msg = {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': f"Observation:{warn_obs} please analyze the attached screenshot and give the Thought and Action. I've provided the tag name of each element and the text it contains (if text exists). Note that <textarea> or <input> may be textbox, but not exactly. Please focus more on the screenshot and then refer to the textual information.\n{web_text}{tabs_text}"},
                    {
                        'type': 'image_url',
                        'image_url': {"url": f"data:image/png;base64,{web_img_b64}"}
                    }
                ]
            }
        else:
            curr_msg = {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': f"Observation: {pdf_obs} Please analyze the response given by Assistant, then consider whether to continue iterating or not. The screenshot of the current page is also attached, give the Thought and Action. I've provided the tag name of each element and the text it contains (if text exists). Note that <textarea> or <input> may be textbox, but not exactly. Please focus more on the screenshot and then refer to the textual information.\n{web_text}{tabs_text}"},
                    {
                        'type': 'image_url',
                        'image_url': {"url": f"data:image/png;base64,{web_img_b64}"}
                    }
                ]
            }
        return curr_msg


def format_msg_text_only_gpt5(it, init_msg, pdf_obs, warn_obs, ac_tree, tabs_info=None):
    """Format text-only messages for GPT API (using accessibility tree) and tab information."""
    # Add tab information to the message
    tabs_text = ""
    if tabs_info:
        tabs_text = "\n\nOpen Tabs:\n"
        for handle, info in tabs_info.items():
            current_indicator = " (CURRENT)" if info['is_current'] else ""
            tabs_text += f"- {info['title']}: {info['url']}{current_indicator}\n"
    
    if it == 1:
        init_msg_format = {
            'role': 'user',
            'content': init_msg + tabs_text + '\n' + ac_tree
        }
        return init_msg_format
    else:
        if not pdf_obs:
            curr_msg = {
                'role': 'user',
                'content': f"Observation:{warn_obs} please analyze the accessibility tree and give the Thought and Action.\n{ac_tree}{tabs_text}"
            }
        else:
            curr_msg = {
                'role': 'user',
                'content': f"Observation: {pdf_obs} Please analyze the response given by Assistant, then consider whether to continue iterating or not. The accessibility tree of the current page is also given, give the Thought and Action.\n{ac_tree}{tabs_text}"
            }
        return curr_msg


def format_msg_text_only_claude(it, init_msg, pdf_obs, warn_obs, ac_tree, tabs_info=None):
    """Format text-only messages for Claude API (using accessibility tree) and tab information."""
    # Add tab information to the message
    tabs_text = ""
    if tabs_info:
        tabs_text = "\n\nOpen Tabs:\n"
        for handle, info in tabs_info.items():
            current_indicator = " (CURRENT)" if info['is_current'] else ""
            tabs_text += f"- {info['title']}: {info['url']}{current_indicator}\n"
    
    if it == 1:
        init_msg_format = {
            'role': 'user',
            'content': init_msg + tabs_text + '\n' + ac_tree
        }
        return init_msg_format
    else:
        if not pdf_obs:
            curr_msg = {
                'role': 'user',
                'content': f"Observation:{warn_obs} please analyze the accessibility tree and give the Thought and Action.\n{ac_tree}{tabs_text}"
            }
        else:
            curr_msg = {
                'role': 'user',
                'content': f"Observation: {pdf_obs} Please analyze the response given by Assistant, then consider whether to continue iterating or not. The accessibility tree of the current page is also given, give the Thought and Action.\n{ac_tree}{tabs_text}"
            }
        return curr_msg


def format_msg_gemini(it, init_msg, pdf_obs, warn_obs, web_img_b64, web_text, tabs_info=None):
    """Format messages for Gemini API with vision support and tab information."""
    from google.genai import types
    import base64
    
    # Add tab information to the message
    tabs_text = ""
    if tabs_info:
        tabs_text = "\n\nOpen Tabs:\n"
        for handle, info in tabs_info.items():
            current_indicator = " (CURRENT)" if info['is_current'] else ""
            tabs_text += f"- {info['title']}: {info['url']}{current_indicator}\n"
    
    if it == 1:
        text_content = init_msg + f"{tabs_text}\nI've provided the tag name of each element and the text it contains (if text exists). Note that <textarea> or <input> may be textbox, but not exactly. Please focus more on the screenshot and then refer to the textual information.\n{web_text}"
        
        # Create image part from base64 data
        image_part = types.Part.from_bytes(
            data=base64.b64decode(web_img_b64),
            mime_type="image/png"
        )
        
        # Return properly formatted message dictionary
        return {
            'role': 'user',
            'content': [text_content, image_part]
        }
    else:
        if not pdf_obs:
            text_content = f"Observation:{warn_obs} please analyze the attached screenshot and give the Thought and Action. I've provided the tag name of each element and the text it contains (if text exists). Note that <textarea> or <input> may be textbox, but not exactly. Please focus more on the screenshot and then refer to the textual information.\n{web_text}{tabs_text}"
        else:
            text_content = f"Observation: {pdf_obs} Please analyze the response given by Assistant, then consider whether to continue iterating or not. The screenshot of the current page is also attached, give the Thought and Action. I've provided the tag name of each element and the text it contains (if text exists). Note that <textarea> or <input> may be textbox, but not exactly. Please focus more on the screenshot and then refer to the textual information.\n{web_text}{tabs_text}"
        
        # Create image part from base64 data
        image_part = types.Part.from_bytes(
            data=base64.b64decode(web_img_b64),
            mime_type="image/png"
        )
        
        # Return properly formatted message dictionary
        return {
            'role': 'user',
            'content': [text_content, image_part]
        }


def format_msg_text_only_gemini(it, init_msg, pdf_obs, warn_obs, ac_tree, tabs_info=None):
    """Format text-only messages for Gemini API (using accessibility tree) and tab information."""
    # Add tab information to the message
    tabs_text = ""
    if tabs_info:
        tabs_text = "\n\nOpen Tabs:\n"
        for handle, info in tabs_info.items():
            current_indicator = " (CURRENT)" if info['is_current'] else ""
            tabs_text += f"- {info['title']}: {info['url']}{current_indicator}\n"
    
    if it == 1:
        content = init_msg + tabs_text + '\n' + ac_tree
    else:
        if not pdf_obs:
            content = f"Observation:{warn_obs} please analyze the accessibility tree and give the Thought and Action.\n{ac_tree}{tabs_text}"
        else:
            content = f"Observation: {pdf_obs} Please analyze the response given by Assistant, then consider whether to continue iterating or not. The accessibility tree of the current page is also given, give the Thought and Action.\n{ac_tree}{tabs_text}"
    
    # Return properly formatted message dictionary
    return {
        'role': 'user',
        'content': content
    }


def call_claude_api(args, anthropic_client, messages):
    """
    Call Claude API with retry logic.
    
    Args:
        args: Arguments containing model configuration
        anthropic_client: Anthropic client instance
        messages: List of message dictionaries
        
    Returns:
        tuple: (prompt_tokens, completion_tokens, error_flag, response)
    """
    retry_times = 0
    while True:
        try:
            if not args.text_only:
                logging.info('Calling Claude API with vision support...')
            else:
                logging.info('Calling Claude API...')
            
            # Convert messages to Anthropic format (remove system message and extract it)
            system_content = ""
            claude_messages = []
            
            for message in messages:
                if message['role'] == 'system':
                    system_content = message['content']
                elif message['role'] in ['user', 'assistant']:
                    claude_messages.append(message)
            
            # Default model if not specified or if using an OpenAI model name
            model = args.api_model
            max_tokens=8192
            claude_response = anthropic_client.messages.create(
                model=model,
                max_tokens=max_tokens,  # Anthropic's max_tokens parameter
                messages=claude_messages,
                system=system_content if system_content else None,
                temperature=args.temperature,
                thinking={'type': 'adaptive', 'budget_tokens': 5000}, 
                output_config={'effort': 'medium'}
            )
            
            print(claude_response.model_dump_json(indent=2))

            # Extract token usage from Claude response
            usage = claude_response.usage
            prompt_tokens = usage.input_tokens if usage else 0
            completion_tokens = usage.output_tokens if usage else 0

            logging.info(f'Prompt Tokens: {prompt_tokens}; Completion Tokens: {completion_tokens}')

            claude_call_error = False
            return prompt_tokens, completion_tokens, claude_call_error, claude_response

        except Exception as e:
            logging.info(f'Error occurred, retrying. Error type: {type(e).__name__}')

            if 'rate_limit' in str(e).lower() or type(e).__name__ == 'RateLimitError':
                time.sleep(10)
            elif 'api_error' in str(e).lower() or type(e).__name__ == 'APIError':
                time.sleep(15)
            elif 'invalid_request' in str(e).lower() or type(e).__name__ == 'InvalidRequestError':
                claude_call_error = True
                return None, None, claude_call_error, None
            else:
                claude_call_error = True
                return None, None, claude_call_error, None

        retry_times += 1
        if retry_times == 10:
            logging.info('Retrying too many times')
            return None, None, True, None


def call_gpt5_api(args, openai_client, messages):
    """
    Call GPT/Azure OpenAI API with retry logic.
    
    Args:
        args: Arguments containing model configuration
        openai_client: OpenAI client instance
        messages: List of message dictionaries
        
    Returns:
        tuple: (prompt_tokens, completion_tokens, error_flag, response)
    """
    retry_times = 0
    while True:
        try:
            if not args.text_only:
                logging.info('Calling Azure OpenAI API with vision support...')
            else:
                logging.info('Calling Azure OpenAI API...')
            if 'gpt-5' in args.api_model:
                max_completion_tokens = 100000
            else:
                max_completion_tokens = 16384
            
            # Build API call params
            api_params = {
                'model': args.api_model,
                'messages': messages,
                'max_completion_tokens': max_completion_tokens,
                'temperature': args.temperature,
                'stream': False
            }

            # Reasoning models (GPT-5 family) take a reasoning_effort knob
            if 'gpt-5' in args.api_model:
                api_params['reasoning_effort'] = 'high'

            # Azure OpenAI supports stop=None, direct OpenAI does not
            if getattr(args, 'run_gpt_with_azure', False):
                api_params['stop'] = None
            
            openai_response = openai_client.chat.completions.create(**api_params)
            print(openai_response.to_json())

            # Extract actual token usage from Azure OpenAI response
            usage = openai_response.usage
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0

            logging.info(f'Prompt Tokens: {prompt_tokens}; Completion Tokens: {completion_tokens}')

            gpt_call_error = False
            return prompt_tokens, completion_tokens, gpt_call_error, openai_response

        except Exception as e:
            logging.info(f'Error occurred, retrying. Error type: {type(e).__name__}')
            logging.info(f'Full error message: {str(e)}')

            if type(e).__name__ == 'RateLimitError':
                time.sleep(10)

            elif type(e).__name__ == 'APIError':
                time.sleep(15)

            elif type(e).__name__ == 'InvalidRequestError' or 'BadRequestError' in type(e).__name__:
                logging.error(f'Invalid/Bad Request Error - Full details: {str(e)}')
                gpt_call_error = True
                return None, None, gpt_call_error, None

            else:
                gpt_call_error = True
                return None, None, gpt_call_error, None

        retry_times += 1
        if retry_times == 10:
            logging.info('Retrying too many times')
            return None, None, True, None


def call_gemini_api(args, gemini_client, messages):
    """
    Call Gemini API with retry logic.
    
    Args:
        args: Arguments containing model configuration
        gemini_client: Gemini client instance
        messages: List of message dictionaries or formatted content for Gemini
        
    Returns:
        tuple: (prompt_tokens, completion_tokens, error_flag, response)
    """
    from google.genai import types

    # Build generate content config

    if '2.5' in args.api_model and 'gemini' in args.api_model: 
        config_params = {
            'temperature': args.temperature,
            'max_output_tokens': 100000,
            'thinking_config': types.ThinkingConfig(thinking_budget=-1) #dynamic thinking budget
        }

    elif '3' in args.api_model and 'gemini' in args.api_model:
        config_params = {
            'temperature': args.temperature,
            'max_output_tokens': 100000,
            'thinking_config': types.ThinkingConfig(thinking_level='high')
        }

    elif 'gemma' in args.api_model:
        config_params = {
            'temperature': args.temperature,
            'max_output_tokens': 100000,
        }

    generate_content_config = types.GenerateContentConfig(**config_params)

    retry_times = 0
    while True:
        try:
            if not args.text_only:
                logging.info('Calling Gemini API with vision support...')
            else:
                logging.info('Calling Gemini API...')
            
            # Extract system message and convert to Gemini Content format
            system_content = ""
            gemini_contents = []
            first_user_message_found = False
            
            for message in messages:
                if message['role'] == 'system':
                    system_content = message['content']
                elif message['role'] == 'user':
                    # For Gemini, user messages need to be in types.Content format
                    if isinstance(message['content'], list):
                        # This is a formatted message from format_msg_gemini
                        # It contains [text_content, image_part]
                        parts = []
                        for item in message['content']:
                            if isinstance(item, str):
                                # Prepend system message to the FIRST user message only
                                if system_content and not first_user_message_found:
                                    combined_text = system_content + "\n\n" + item
                                    parts.append(types.Part.from_text(text=combined_text))
                                    first_user_message_found = True
                                else:
                                    parts.append(types.Part.from_text(text=item))
                            else:
                                # This is already a Part object (image)
                                parts.append(item)
                        gemini_contents.append(types.Content(role="user", parts=parts))
                    else:
                        # This is a simple text message
                        if system_content and not first_user_message_found:
                            # Combine system content with first user message
                            combined_content = system_content + "\n\n" + message['content']
                            gemini_contents.append(types.Content(
                                role="user",
                                parts=[types.Part.from_text(text=combined_content)]
                            ))
                            first_user_message_found = True
                        else:
                            gemini_contents.append(types.Content(
                                role="user",
                                parts=[types.Part.from_text(text=message['content'])]
                            ))
                elif message['role'] == 'assistant':
                    # Add assistant responses as "model" role in Gemini
                    gemini_contents.append(types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=message['content'])]
                    ))
            
            # Debug logging
            logging.info(f"Gemini API: Sending {len(gemini_contents)} Content objects")
            for i, content in enumerate(gemini_contents):
                logging.info(f"Content {i}: role={content.role}, parts_count={len(content.parts)}")
            
            gemini_response = gemini_client.models.generate_content(
                model=args.api_model,
                contents=gemini_contents,
                config=generate_content_config
            )
            
            print(f"Gemini response: {gemini_response.text}")

            # Extract token usage from Gemini response if available
            prompt_tokens = 0
            completion_tokens = 0
            
            if hasattr(gemini_response, 'usage_metadata') and gemini_response.usage_metadata:
                usage = gemini_response.usage_metadata
                prompt_tokens = getattr(usage, 'prompt_token_count', 0)
                completion_tokens = getattr(usage, 'candidates_token_count', 0)
            
            logging.info(f'Prompt Tokens: {prompt_tokens}; Completion Tokens: {completion_tokens}')

            gemini_call_error = False
            if not completion_tokens: #gemma model's response actually gives completion tokens as None causing an error in the run 
                completion_tokens = 0 
            if not prompt_tokens:
                prompt_tokens = 0 
            return prompt_tokens, completion_tokens, gemini_call_error, gemini_response

        except Exception as e:
            logging.info(f'Error occurred, retrying. Error type: {type(e).__name__}')

            if 'quota' in str(e).lower() or 'rate' in str(e).lower():
                time.sleep(10)
            elif 'api' in str(e).lower():
                time.sleep(15)
            elif 'invalid' in str(e).lower():
                gemini_call_error = True
                return None, None, gemini_call_error, None
            else:
                gemini_call_error = True
                return None, None, gemini_call_error, None

        retry_times += 1
        if retry_times == 10:
            logging.info('Retrying too many times')
            return None, None, True, None

