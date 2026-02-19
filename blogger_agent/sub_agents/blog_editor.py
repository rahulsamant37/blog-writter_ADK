from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools import FunctionTool

from ..agent_utils import suppress_output_callback
from ..config import config
from ..tools import readability_scorer

blog_editor = LlmAgent(
    model=config.critic_model,
    name="blog_editor",
    description="Edits a technical blog post based on user feedback.",
    instruction="""
    You are a professional technical editor. You will be given a blog post and user feedback.
    Your task is to edit the blog post based on the provided feedback.
    If the user asks for readability improvements, you can use the `readability_scorer` tool to identify complex sentences and long paragraphs.
    The final output should be a revised blog post in Markdown format.
    """,
    tools=[FunctionTool(readability_scorer)],
    output_key="blog_post",
    after_agent_callback=suppress_output_callback,
)
