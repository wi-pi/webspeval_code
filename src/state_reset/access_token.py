"""
This script is used to take the instruction and replace the four digit number in the task instructionwith a random number.
"""


import random 
import re
from typing import List
from .extension_reset import load_json_file, save_json_file

def hf_random_access_token_number(instruction=None):
    """
    This function is used to replace the four digit number in the task instruction with a random number.
    Keep the state of the already used numbers in the file 'access_token_numbers.json'
    """
    
    four_digit_number = re.search(r'\{(\d{4})\}', instruction)
    already_used_numbers : List[int] = load_json_file('access_token_numbers.json')
    if four_digit_number:
        four_digit_number = four_digit_number.group(1)
        new_number = random.choice([num for num in range(1000, 9999) if num not in already_used_numbers])
        already_used_numbers.append(new_number)
        save_json_file('access_token_numbers.json', already_used_numbers)
        return instruction.replace(four_digit_number, str(new_number))
    else:
        return instruction
