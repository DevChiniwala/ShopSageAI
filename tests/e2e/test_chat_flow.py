import pytest
from playwright.sync_api import Page, expect
import time

# To run this locally, ensure the server is running on http://127.0.0.1:8000
BASE_URL = "http://127.0.0.1:8000"

def test_homepage_loads(page: Page):
    """Test that the frontend loads successfully."""
    page.goto(BASE_URL)
    
    # Check for main title
    expect(page.locator("h1")).to_contain_text("ShopSage AI")
    
    # Check that chat container exists
    chat_box = page.locator("#chat-box")
    expect(chat_box).to_be_visible()

def test_chat_interaction(page: Page):
    """Test a basic chat interaction with the bot."""
    page.goto(BASE_URL)
    
    # Find input and send button
    user_input = page.locator("#user-input")
    send_button = page.locator("button:has-text('Send')")
    
    # Ensure they are enabled
    expect(user_input).to_be_enabled()
    expect(send_button).to_be_enabled()
    
    # Type a greeting
    test_message = "Hello! I am a Playwright test."
    user_input.fill(test_message)
    
    # Verify the text was entered
    expect(user_input).to_have_value(test_message)
    
    # Send the message
    send_button.click()
    
    # Check that user message appeared in the chat box
    # The user message has class .user-message
    user_msg_elem = page.locator(".user-message").last
    expect(user_msg_elem).to_contain_text(test_message)
    
    # Wait for bot response (might take a second depending on the mock/API)
    # The bot message has class .bot-message
    bot_msg_elem = page.locator(".bot-message").last
    
    # Increase timeout since API calls might take time
    expect(bot_msg_elem).to_be_visible(timeout=10000)
    
    # At least some text should be returned
    text_content = bot_msg_elem.text_content()
    assert text_content is not None
    assert len(text_content.strip()) > 0
