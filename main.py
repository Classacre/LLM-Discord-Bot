import os
import discord
from discord.ext import commands
from poe_api_wrapper import PoeApi
import asyncio
import logging
import json

# Configure logging
logging.basicConfig(level=logging.INFO)

# Fetch environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
POE_PB = os.getenv('POE_PB')
POE_PLAT = os.getenv('POE_PLAT')
GUILD_ID = os.getenv('GUILD_ID')

# Validate Environment Variables
if not all([DISCORD_TOKEN, POE_PB, POE_PLAT, GUILD_ID]):
    logging.error("One or more environment variables are missing. Please check your Replit Secrets.")
    exit(1)

try:
    GUILD_ID = int(GUILD_ID)
except ValueError:
    logging.error("GUILD_ID must be an integer.")
    exit(1)

# Initialize PoeApi client
poe_client = PoeApi(tokens={
    'p-b': POE_PB,
    'p-lat': POE_PLAT
})

# File to store guild-specific LLM choices and chat IDs
LLM_CHOICES_FILE = 'llm_choices.json'

# Load existing LLM choices from the file, if it exists
if os.path.exists(LLM_CHOICES_FILE):
    with open(LLM_CHOICES_FILE, 'r') as f:
        try:
            llm_choices = json.load(f)
        except json.JSONDecodeError:
            logging.error(f"Failed to decode {LLM_CHOICES_FILE}. Resetting to default.")
            llm_choices = {}
else:
    llm_choices = {}

# Function to save LLM choices to the file
def save_llm_choices():
    with open(LLM_CHOICES_FILE, 'w') as f:
        json.dump(llm_choices, f, indent=4)

# Migration: Convert string entries to dicts if necessary
def migrate_llm_choices():
    migrated = False
    for guild_id, data in list(llm_choices.items()):
        if isinstance(data, str):
            llm_choices[guild_id] = {
                'model': data,
                'chatId': None  # Initialize chatId as None
            }
            migrated = True
            logging.info(f"Migrated guild_id {guild_id} to new format.")
    return migrated

# Perform migration if needed
if migrate_llm_choices():
    save_llm_choices()

# Ensure the default guild has a default LLM and chatId
if str(GUILD_ID) not in llm_choices:
    llm_choices[str(GUILD_ID)] = {
        'model': 'gpt3_5',  # Default model
        'chatId': None       # No chat initially
    }

# Function to get all available models (synchronous)
def get_available_models():
    try:
        # Assuming `get_available_bots` returns a dictionary of available bots/models
        bots = poe_client.get_available_bots()
        # Extract the handles of available bots
        models = list(bots.keys())
        logging.info("Retrieved available models successfully.")
        return models
    except Exception as e:
        logging.error(f"Error fetching available models: {e}")
        return []

# Function to get Poe API settings
def get_poe_settings():
    try:
        settings = poe_client.get_settings()
        logging.info("Retrieved Poe API settings successfully.")
        return settings
    except Exception as e:
        logging.error(f"Error fetching Poe API settings: {e}")
        return {}

# Function to get bot info
def get_bot_info(bot_handle):
    try:
        bot_info = poe_client.get_botInfo(handle=bot_handle)
        logging.info(f"Retrieved bot info for {bot_handle} successfully.")
        return bot_info
    except Exception as e:
        logging.error(f"Error fetching bot info for {bot_handle}: {e}")
        return {}

# Configure Discord Intents
intents = discord.Intents.default()
intents.message_content = True  # Ensure the bot can read message content

# Initialize Discord bot
bot = commands.Bot(command_prefix='!', intents=intents)

# Create a Tree for slash commands
tree = bot.tree

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    try:
        # Register slash commands to a specific guild for immediate syncing
        guild = discord.Object(id=GUILD_ID)
        tree.copy_global_to(guild=guild)
        synced = await tree.sync(guild=guild)  # Sync commands to the specified guild
        logging.info(f'Successfully synced {len(synced)} command(s) to guild {GUILD_ID}')
    except Exception as e:
        logging.error(f'Error syncing commands: {e}')

@tree.command(
    name="askpoe",
    description="Send a prompt to Poe.com and receive a reply.",
    guild=discord.Object(id=GUILD_ID)
)
async def askpoe(interaction: discord.Interaction, prompt: str):
    logging.info(f'Received prompt from {interaction.user}: {prompt}')
    await interaction.response.send_message("⚙️ Processing your request...", ephemeral=True)

    try:
        # Get the selected model and chatId for this guild
        guild_id = str(interaction.guild_id)
        model_info = llm_choices.get(guild_id, {'model': 'gpt3_5', 'chatId': None})

        # Validate that model_info is a dict
        if isinstance(model_info, str):
            # Migrate the entry
            model_info = {
                'model': model_info,
                'chatId': None
            }
            llm_choices[guild_id] = model_info
            save_llm_choices()
            logging.info(f"Migrated guild_id {guild_id} within /askpoe command.")

        bot_handle = model_info['model']
        chat_id = model_info.get('chatId')  # Using 'chatId'

        # Send the prompt to Poe API and get the response
        response = ""
        # Wrap the generator to make it an async iterator
        async for chunk in async_generator(poe_client.send_message(bot_handle, prompt, chatId=chat_id)):
            if isinstance(chunk, dict):
                partial_response = chunk.get("response", "")
                if partial_response:
                    response += partial_response
                # Update chatId if a new chat is created
                new_chat_id = chunk.get("chatId")
                if new_chat_id:
                    llm_choices[guild_id]['chatId'] = new_chat_id
                    save_llm_choices()
            else:
                logging.warning(f"Unexpected chunk format: {chunk}")

        if response:
            # Format the message with username and model name
            # Example:
            # **Username:** Your prompt here
            # **Model Name:** Model's reply here

            formatted_message = f"**{interaction.user.display_name}:** {prompt}\n**{model_info['model']}:** {response}"

            if len(formatted_message) <= 2000:
                await interaction.followup.send(formatted_message)
            else:
                # Calculate the length that can be sent after prefix
                prefix = f"**{interaction.user.display_name}:** {prompt}\n**{model_info['model']}:** "
                max_chunk_size = 2000 - len(prefix)

                # Ensure max_chunk_size is positive
                if max_chunk_size <= 0:
                    await interaction.followup.send('❌ The combined prompt and reply are too long to display.')
                else:
                    # Send the first chunk with prefix
                    first_chunk = response[:max_chunk_size]
                    await interaction.followup.send(f"{prefix}{first_chunk}")

                    # Send remaining chunks without prefix
                    for i in range(max_chunk_size, len(response), 2000):
                        chunk = response[i:i+2000]
                        await interaction.followup.send(f"{chunk}")

            logging.info(f'Sent response to {interaction.user}')
        else:
            await interaction.followup.send('❌ Sorry, I could not generate a response.')
            logging.warning(f'No response generated for {interaction.user}')
    except TypeError as te:
        logging.error(f"TypeError processing request: {te}")
        await interaction.followup.send('❌ There was a type error processing your request. Please contact the developer.')
    except Exception as e:
        logging.error(f'Error processing request: {e}')
        await interaction.followup.send('❌ Sorry, there was an error processing your request. Please try again later.')

# Optional: Help Command
@tree.command(
    name="help",
    description="Display available commands.",
    guild=discord.Object(id=GUILD_ID)
)
async def help_command(interaction: discord.Interaction):
    help_text = """
    **PoeBot Commands:**
    `/askpoe prompt: <your prompt>` - Send a prompt to Poe.com and receive a reply.
    `/llm-list` - List all available LLM models.
    `/llm-set model: <model name>` - Set your preferred LLM model.
    `/reset` - Reset the conversation thread.
    `/info` - Display Poe API settings and current model information.
    `/clear` - Clear the conversation context.
    `/help` - Display this help message.
    """
    await interaction.response.send_message(help_text, ephemeral=True)

@tree.command(
    name="llm-list",
    description="List all available LLM models.",
    guild=discord.Object(id=GUILD_ID)
)
async def llm_list(interaction: discord.Interaction):
    logging.info(f'LLM list requested by {interaction.user}')
    await interaction.response.send_message("🔍 Fetching available LLM models...", ephemeral=True)

    try:
        # Run the synchronous get_available_models in a separate thread
        models = await asyncio.to_thread(get_available_models)
        if models:
            model_list = "\n".join([f"- {model}" for model in models])
            response_text = f"**Available LLM Models:**\n{model_list}"
            await interaction.followup.send(response_text)
            logging.info(f'Sent LLM list to {interaction.user}')
        else:
            await interaction.followup.send('❌ No available models found.')
            logging.warning(f'No models found when requested by {interaction.user}')
    except Exception as e:
        logging.error(f'Error fetching LLM list: {e}')
        await interaction.followup.send('❌ Sorry, there was an error fetching the models.')

@tree.command(
    name="llm-set",
    description="Set your preferred LLM model.",
    guild=discord.Object(id=GUILD_ID)
)
async def llm_set(interaction: discord.Interaction, model: str):
    logging.info(f'LLM set requested by {interaction.user}: {model}')
    await interaction.response.send_message("⚙️ Setting your preferred LLM model...", ephemeral=True)

    try:
        # Run the synchronous get_available_models in a separate thread
        models = await asyncio.to_thread(get_available_models)
        if model not in models:
            await interaction.followup.send(f"❌ `{model}` is not a valid model. Use `/llm-list` to see all available models.")
            logging.warning(f'Invalid model attempted by {interaction.user}: {model}')
            return

        # Set the model for the guild and reset chatId
        guild_id = str(interaction.guild_id)
        current_info = llm_choices.get(guild_id)

        if isinstance(current_info, str):
            # Migrate the entry
            llm_choices[guild_id] = {
                'model': model,
                'chatId': None
            }
            logging.info(f"Migrated guild_id {guild_id} within /llm-set command.")
        else:
            llm_choices[guild_id]['model'] = model
            llm_choices[guild_id]['chatId'] = None  # Reset chat when changing model

        save_llm_choices()  # Persist the change
        await interaction.followup.send(f"✅ Your preferred LLM model has been set to `{model}`.")
        logging.info(f'Set model for guild {guild_id} to {model} by {interaction.user}')
    except Exception as e:
        logging.error(f'Error setting LLM model: {e}')
        await interaction.followup.send('❌ Sorry, there was an error setting your preferred model. Please try again later.')

@tree.command(
    name="reset",
    description="Reset the conversation thread.",
    guild=discord.Object(id=GUILD_ID)
)
async def reset(interaction: discord.Interaction):
    logging.info(f'Reset requested by {interaction.user}')
    await interaction.response.send_message("🧹 Resetting the conversation thread...", ephemeral=True)

    try:
        guild_id = str(interaction.guild_id)
        if guild_id in llm_choices:
            # Ensure the entry is a dict
            if isinstance(llm_choices[guild_id], str):
                llm_choices[guild_id] = {
                    'model': llm_choices[guild_id],
                    'chatId': None
                }
                logging.info(f"Migrated guild_id {guild_id} within /reset command.")

            llm_choices[guild_id]['chatId'] = None
            save_llm_choices()
            await interaction.followup.send("✅ The conversation has been reset. The next prompt will start a new conversation.")
            logging.info(f'Conversation thread reset for guild {guild_id} by {interaction.user}')
        else:
            await interaction.followup.send("❌ Guild not found.")
            logging.warning(f'Guild {guild_id} not found when reset was requested by {interaction.user}')
    except Exception as e:
        logging.error(f'Error resetting conversation thread: {e}')
        await interaction.followup.send('❌ Sorry, there was an error resetting the conversation. Please try again later.')

@tree.command(
    name="info",
    description="Display Poe API settings and current model information.",
    guild=discord.Object(id=GUILD_ID)
)
async def info(interaction: discord.Interaction):
    logging.info(f'Info requested by {interaction.user}')
    await interaction.response.send_message("📄 Fetching Poe API settings and model information...", ephemeral=True)

    try:
        # Fetch Poe API settings
        settings = await asyncio.to_thread(get_poe_settings)
        if not settings:
            await interaction.followup.send("❌ Failed to retrieve Poe API settings.")
            logging.warning(f'Failed to retrieve Poe API settings for {interaction.user}')
            return

        # Get current model information
        guild_id = str(interaction.guild_id)
        model_info = llm_choices.get(guild_id, {'model': 'gpt3_5', 'chatId': None})

        if isinstance(model_info, str):
            model_info = {
                'model': model_info,
                'chatId': None
            }
            llm_choices[guild_id] = model_info
            save_llm_choices()
            logging.info(f"Migrated guild_id {guild_id} within /info command.")

        bot_handle = model_info['model']
        bot_info = await asyncio.to_thread(get_bot_info, bot_handle)

        # Replace 'GPT-4' with the currently equipped model's handle
        if bot_info:
            formatted_bot_handle = bot_info.get('handle', 'Unknown Model')
            formatted_bot_info = f"""
**Poe API Settings:**
- **numRemainingMessages**: {settings.get('numRemainingMessages', 'N/A')}
- **subscriptionTier**: {settings.get('subscriptionTier', 'N/A')}

**Current Model Information:**
- **Handle**: {formatted_bot_handle}
- **Model**: {bot_info.get('model', 'N/A')}
- **Supports File Upload**: {bot_info.get('supportsFileUpload', False)}
- **Message Timeout (secs)**: {bot_info.get('messageTimeoutSecs', 'N/A')}
- **Display Message Point Price**: {bot_info.get('displayMessagePointPrice', 'N/A')}
- **Number of Remaining Messages**: {bot_info.get('numRemainingMessages', 'N/A')}
- **Viewer is Creator**: {bot_info.get('viewerIsCreator', False)}
- **ID**: {bot_info.get('id', 'N/A')}
"""
        else:
            formatted_bot_info = "❌ Unable to retrieve current model information."

        await interaction.followup.send(formatted_bot_info)
        logging.info(f'Sent info to {interaction.user}')
    except Exception as e:
        logging.error(f'Error fetching info: {e}')
        await interaction.followup.send('❌ Sorry, there was an error fetching the info. Please try again later.')

@tree.command(
    name="clear",
    description="Clear the conversation context.",
    guild=discord.Object(id=GUILD_ID)
)
async def clear(interaction: discord.Interaction):
    logging.info(f'Clear requested by {interaction.user}')
    await interaction.response.send_message("🧹 Clearing the conversation context...", ephemeral=True)

    try:
        guild_id = str(interaction.guild_id)
        model_info = llm_choices.get(guild_id)

        if not model_info or not isinstance(model_info, dict):
            await interaction.followup.send("❌ No conversation context found to clear.")
            logging.warning(f'No conversation context found for guild {guild_id} when clear was requested by {interaction.user}')
            return

        bot_handle = model_info['model']
        chat_id = model_info.get('chatId')

        if not chat_id:
            await interaction.followup.send("❌ No active conversation thread to clear.")
            logging.warning(f'No active chatId found for guild {guild_id} when clear was requested by {interaction.user}')
            return

        # Clear the conversation context using chat_break
        await asyncio.to_thread(poe_client.chat_break, bot_handle, chatId=chat_id)

        # Reset the chatId
        llm_choices[guild_id]['chatId'] = None
        save_llm_choices()

        await interaction.followup.send("✅ The conversation context has been cleared.")
        logging.info(f'Cleared conversation context for guild {guild_id} by {interaction.user}')
    except Exception as e:
        logging.error(f'Error clearing conversation context: {e}')
        await interaction.followup.send('❌ Sorry, there was an error clearing the conversation context. Please try again later.')

def async_generator(gen):
    """Wrap a generator to make it an async iterator."""
    async def async_gen():
        for item in gen:
            yield item
            await asyncio.sleep(0)  # Yield control to the event loop
    return async_gen()

@tree.command(
    name="reload",
    description="Reload the bot's commands (Developer Only).",
    guild=discord.Object(id=GUILD_ID)
)
@commands.is_owner()
async def reload_bot(interaction: discord.Interaction):
    """Reload the bot's commands."""
    try:
        await tree.sync(guild=discord.Object(id=GUILD_ID))
        await interaction.response.send_message("✅ Bot commands reloaded successfully.", ephemeral=True)
        logging.info(f'Commands reloaded by {interaction.user}')
    except Exception as e:
        logging.error(f'Error reloading commands: {e}')
        await interaction.response.send_message("❌ Failed to reload commands.", ephemeral=True)

# Run Discord Bot
bot.run(DISCORD_TOKEN)