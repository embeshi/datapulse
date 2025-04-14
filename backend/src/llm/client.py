# src/llm/client.py

import os
import logging
from typing import Optional, Dict, List, Any
import openai
from openai import OpenAI, APIError, RateLimitError, AuthenticationError # Import specific errors
from dotenv import load_dotenv # Import load_dotenv
import time

# --- Configuration ---
# Explicitly load .env.local if that's your filename
# If your file is just .env, then load_dotenv() is fine.
dotenv_path = '.env.local' # CHANGE THIS if your file is named differently (e.g., '.env')
if load_dotenv(dotenv_path=dotenv_path):
     logging.info(f"Loaded environment variables from {dotenv_path}")
else:
     logging.warning(f"Could not find {dotenv_path} file.")

# Configure logging (ensure this runs before potential errors below)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Initialize OpenAI Client ---
# Make initialization failure more explicit
client: Optional[OpenAI] = None # Initialize as None
try:
    # Explicitly check if the key was loaded
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not found in environment variables.")
        # Optionally raise an error here to stop execution if key is mandatory
        raise ValueError("OPENAI_API_KEY is required but not set.")
    else:
         # You can mask the key partially if logging for debug
         logger.info(f"Found OpenAI API Key (masked): sk-...{api_key[-4:]}")

    # Initialize client (this will use the key loaded into the environment)
    client = OpenAI()
    # Optional: Test connection (uncomment if needed, might incur small cost/time)
    # openai_client.models.list()
    logger.info("OpenAI client initialized successfully.")

except AuthenticationError as e:
    logger.error(f"OpenAI Authentication Error: {e}. Check your API key.")
    # Stop execution if authentication fails
    raise SystemExit(f"Failed to initialize OpenAI client due to AuthenticationError: {e}") from e
except APIError as e:
    logger.error(f"OpenAI API Error during initialization: {e}.")
    raise SystemExit(f"Failed to initialize OpenAI client due to APIError: {e}") from e
except Exception as e:
    logger.error(f"Unexpected error initializing OpenAI client: {e}")
    raise SystemExit(f"Unexpected error initializing OpenAI client: {e}") from e


# --- Basic In-Memory Conversation History Store ---
# WARNING: Not suitable for production! Resets on app restart, not scalable.
# Needs replacement with a persistent store (e.g., Redis, DB) for real use.
LLM_CONVERSATION_HISTORY: Dict[str, List[Dict[str, str]]] = {}
logger.warning("Using basic in-memory LLM_CONVERSATION_HISTORY. History will be lost on restart.")
# ---------------------------------------------------

# --- Constants ---
LLM_MODEL = "gpt-4o"
LLM_TEMPERATURE = 0.7
MAX_HISTORY_TOKENS = 3000 # Rough estimate, tune as needed to prevent context overflow
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 3


def _estimate_token_count(messages: List[Dict[str, str]]) -> int:
    """Very basic token estimation (underestimates usually). Replace with tiktoken if precision needed."""
    count = 0
    for message in messages:
        count += len(message.get("content", "")) // 3 # Rough approximation
    return count


def call_llm(prompt: str, conversation_id: Optional[str] = None) -> str:
    """
    Calls the OpenAI LLM (gpt-4o) mimicking the get_answer interface.
    Manages conversation history in memory based on conversation_id.

    Args:
        prompt (str): The user's current prompt/message.
        conversation_id (Optional[str]): Identifier to maintain conversation context.

    Returns:
        str: The LLM's text response.

    Raises:
        Exception: If the LLM API call fails after retries.
    """
    logger.info(f"Calling LLM (Model: {LLM_MODEL}, Temp: {LLM_TEMPERATURE}, ConvID: {conversation_id})")
    if len(prompt) > 300:
        logger.debug(f"LLM User Prompt (start): {prompt[:300]}...")
    else:
        logger.debug(f"LLM User Prompt: {prompt}")

    messages: List[Dict[str, str]] = []
    if conversation_id:
        messages = LLM_CONVERSATION_HISTORY.get(conversation_id, []).copy() # Get history if exists
        # Basic context window management (remove oldest messages if too long)
        # A more sophisticated approach would use tiktoken for accurate counting
        while len(messages) > 1 and _estimate_token_count(messages) > MAX_HISTORY_TOKENS:
             logger.warning(f"Trimming conversation history for ConvID: {conversation_id}")
             messages.pop(0) # Remove the oldest message (after potential system prompt)
             if messages and messages[0]['role'] == 'assistant': # Avoid starting with assistant msg
                 messages.pop(0)

    # Add the current user prompt
    messages.append({"role": "user", "content": prompt})

    retries = 0
    while retries <= MAX_RETRIES:
        try:
            logger.debug(f"Attempt {retries+1}/{MAX_RETRIES+1}. Sending {len(messages)} messages to OpenAI.")
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=LLM_TEMPERATURE,
                # max_tokens=1000, # Optional: Limit response length
                # Add other parameters like top_p, presence_penalty if needed
            )

            assistant_response = response.choices[0].message.content
            assistant_response = assistant_response.strip() if assistant_response else ""

            logger.info(f"LLM call successful. Response length: {len(assistant_response)}")
            if len(assistant_response) > 300:
                logger.debug(f"LLM Response (start): {assistant_response[:300]}...")
            else:
                logger.debug(f"LLM Response: {assistant_response}")

            # If using conversation ID, store the history
            if conversation_id:
                messages.append({"role": "assistant", "content": assistant_response})
                LLM_CONVERSATION_HISTORY[conversation_id] = messages
                logger.debug(f"Updated history for ConvID: {conversation_id}. History length: {len(messages)}")

            return assistant_response

        except RateLimitError as e:
            retries += 1
            logger.warning(f"Rate limit error calling OpenAI (Attempt {retries}/{MAX_RETRIES+1}): {e}. Retrying in {RETRY_DELAY_SECONDS}s...")
            if retries > MAX_RETRIES:
                logger.error("Max retries exceeded for rate limit error.")
                raise Exception(f"LLM Rate Limit Error after {MAX_RETRIES} retries: {e}") from e
            time.sleep(RETRY_DELAY_SECONDS)
        except APIError as e:
            logger.error(f"OpenAI API Error: {e}")
            raise Exception(f"LLM API Error: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error calling LLM: {e}")
            raise Exception(f"Unexpected error during LLM call: {e}") from e

    # Should not be reachable if MAX_RETRIES >= 0, but as a safeguard
    raise Exception("LLM call failed after exhausting retries.")


# Example Usage (Requires OPENAI_API_KEY to be set in .env or environment)
if __name__ == "__main__":
    logger.info("\n--- Testing OpenAI LLM Client ---")

    # Test 1: Initial call in a conversation
    conv_id = "test_conv_001"
    prompt1 = "My favorite color is blue. What is yours?"
    logger.info(f"\n[Test 1: Initial Prompt, ConvID: {conv_id}]")
    try:
        response1 = call_llm(prompt1, conversation_id=conv_id)
        print(f"Response 1: {response1}")
    except Exception as e:
        logger.error(f"Test 1 failed: {e}")

    # Test 2: Follow-up call using the same conversation ID
    prompt2 = "Based on our previous exchange, what color did I say was my favorite?"
    logger.info(f"\n[Test 2: Follow-up Prompt, ConvID: {conv_id}]")
    try:
        # Allow some time if rate limits are strict
        # time.sleep(1)
        response2 = call_llm(prompt2, conversation_id=conv_id)
        print(f"Response 2: {response2}")
        # Check if the response correctly references "blue"
        if "blue" not in response2.lower():
             logger.warning("LLM might not have used context correctly in Test 2.")
    except Exception as e:
        logger.error(f"Test 2 failed: {e}")

    # Test 3: Call without conversation ID (stateless)
    prompt3 = "What is the capital of France?"
    logger.info(f"\n[Test 3: Stateless Prompt]")
    try:
        response3 = call_llm(prompt3)
        print(f"Response 3: {response3}")
    except Exception as e:
        logger.error(f"Test 3 failed: {e}")

    # Verify history was stored for conv_id
    if conv_id in LLM_CONVERSATION_HISTORY:
         logger.info(f"\nStored history for {conv_id}:")
         for msg in LLM_CONVERSATION_HISTORY[conv_id]:
             print(f"- {msg['role']}: {msg['content'][:80]}...") # Print truncated history
    else:
         logger.warning(f"No history found for {conv_id} after tests.")


    logger.info("\n--- OpenAI LLM Client Tests Complete ---")