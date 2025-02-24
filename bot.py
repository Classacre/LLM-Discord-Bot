import os
import discord
from discord.ext import commands
from poe_api_wrapper import PoeApi
import asyncio
import logging
import json
from typing import Dict, Optional
from dataclasses import dataclass, asdict, field
from dotenv import load_dotenv
import time

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

@dataclass
class UserSettings:
    model: str = "gpt3_5"  # Default model
    chat_ids: Dict[str, Optional[str]] = field(default_factory=dict)  # Map of model -> chatId
    conversation_history: list = field(default_factory=list)

    def get_chat_id(self, model: str) -> Optional[str]:
        """Get chat ID for a specific model"""
        return self.chat_ids.get(model)

    def set_chat_id(self, model: str, chat_id: str):
        """Set chat ID for a specific model"""
        self.chat_ids[model] = chat_id

    def clear_chat_id(self, model: str):
        """Clear chat ID for a specific model"""
        if model in self.chat_ids:
            del self.chat_ids[model]

class PoeDiscordBot:
    def __init__(self):
        # Fetch environment variables
        self.discord_token = os.getenv('DISCORD_TOKEN')
        self.poe_pb = os.getenv('POE_PB')
        self.poe_plat = os.getenv('POE_PLAT')
        self.admin_password = os.getenv('ADMIN_PASSWORD')
        
        # Get guild IDs from environment variable (comma-separated list)
        guild_ids_str = os.getenv('GUILD_IDS', '')
        self.guild_ids = [int(gid.strip()) for gid in guild_ids_str.split(',') if gid.strip()]
        
        if not self.guild_ids:
            logging.error("No guild IDs configured. Please set GUILD_IDS in your environment variables.")
            raise ValueError("No guild IDs configured")

        # Validate Environment Variables
        if not all([self.discord_token, self.poe_pb, self.poe_plat]):
            logging.error("Missing environment variables. Please check your configuration.")
            raise ValueError("Missing required environment variables")

        if not self.admin_password:
            logging.warning("ADMIN_PASSWORD not set. Admin purge command will be disabled.")
            self.admin_password = None

        # Initialize PoeApi client
        self.poe_client = PoeApi(tokens={
            'p-b': self.poe_pb,
            'p-lat': self.poe_plat
        })

        # File to store user settings
        self.USER_SETTINGS_FILE = 'user_settings.json'
        self.user_settings: Dict[str, UserSettings] = {}
        self.load_user_settings()

        # Configure Discord Intents
        intents = discord.Intents.default()
        intents.message_content = True

        # Initialize Discord bot
        self.bot = commands.Bot(command_prefix='!', intents=intents)
        self.tree = self.bot.tree

        # Register commands and events
        self.setup_commands()

        # Cache for available models
        self.cached_models = []  # For text/LLM models
        self.cached_image_models = []  # For image generation models
        self.cached_video_models = []  # For video generation models
        self.MODELS_CACHE_FILE = 'models_cache.json'
        self.load_models_cache()

    def load_user_settings(self):
        """Load user settings from file"""
        if os.path.exists(self.USER_SETTINGS_FILE):
            try:
                with open(self.USER_SETTINGS_FILE, 'r') as f:
                    data = json.load(f)
                    self.user_settings = {
                        user_id: UserSettings(**settings)
                        for user_id, settings in data.items()
                    }
            except Exception as e:
                logging.error(f"Error loading user settings: {e}")
                self.user_settings = {}
        else:
            self.user_settings = {}

    def save_user_settings(self):
        """Save user settings to file"""
        try:
            with open(self.USER_SETTINGS_FILE, 'w') as f:
                json.dump(
                    {user_id: asdict(settings) 
                     for user_id, settings in self.user_settings.items()},
                    f,
                    indent=4
                )
        except Exception as e:
            logging.error(f"Error saving user settings: {e}")

    def get_user_settings(self, user_id: str) -> UserSettings:
        """Get settings for a user, creating default if none exist"""
        if user_id not in self.user_settings:
            self.user_settings[user_id] = UserSettings()
            self.save_user_settings()
        return self.user_settings[user_id]

    def load_models_cache(self):
        """Load cached models from file"""
        try:
            if os.path.exists(self.MODELS_CACHE_FILE):
                with open(self.MODELS_CACHE_FILE, 'r') as f:
                    data = json.load(f)
                    self.cached_models = data.get('text', [])
                    self.cached_image_models = data.get('image', [])
                    self.cached_video_models = data.get('video', [])
            else:
                self.cached_models = []
                self.cached_image_models = []
                self.cached_video_models = []
        except Exception as e:
            logging.error(f"Error loading models cache: {e}")
            self.cached_models = []
            self.cached_image_models = []
            self.cached_video_models = []

    def save_models_cache(self):
        """Save cached models to file"""
        try:
            with open(self.MODELS_CACHE_FILE, 'w') as f:
                json.dump({
                    'text': self.cached_models,
                    'image': self.cached_image_models,
                    'video': self.cached_video_models
                }, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving models cache: {e}")

    async def fetch_all_models(self):
        """Fetch all available models and their info"""
        models_data = self.poe_client.get_available_creation_models()
        
        # Process text models
        text_models = models_data.get('text', [])
        text_models.sort(key=str.lower)
        
        # Process image models
        image_models = models_data.get('image', [])
        image_models.sort(key=str.lower)
        
        # Process video models
        video_models = models_data.get('video', [])
        video_models.sort(key=str.lower)
        
        models_info = {
            'text': [],
            'image': [],
            'video': []
        }
        
        # Process text models
        for handle in text_models:
            try:
                # First determine context length from handle name
                context_length = "32K"  # Default
                handle_lower = handle.lower()
                
                # Check for explicit context lengths in name
                if "2m" in handle_lower:
                    context_length = "2M"
                elif "1m" in handle_lower:
                    context_length = "1M"
                elif "200k" in handle_lower:
                    context_length = "200K"
                elif "128k" in handle_lower:
                    context_length = "128K"
                elif "100k" in handle_lower:
                    context_length = "100K"
                
                # Try to get additional model info, but don't fail if we can't
                display_name = handle
                description = ""
                try:
                    bot_info = self.poe_client.get_botInfo(handle=handle)
                    if bot_info:
                        display_name = bot_info.get('displayName', handle)
                        description = bot_info.get('description', '')
                        
                        # If we didn't find context length in name, try to determine from timeout
                        if context_length == "32K" and 'messageTimeoutSecs' in bot_info:
                            timeout_secs = bot_info['messageTimeoutSecs']
                            if timeout_secs >= 60:
                                context_length = "32K"
                            elif timeout_secs >= 30:
                                context_length = "16K"
                            elif timeout_secs >= 15:
                                context_length = "8K"
                            elif timeout_secs >= 10:
                                context_length = "4K"
                            else:
                                context_length = "2K"
                except Exception as e:
                    logging.warning(f"Could not get additional info for model {handle}: {e}")
                    # Continue with default values
                
                models_info['text'].append({
                    "handle": handle,
                    "display_name": display_name,
                    "description": description,
                    "context_length": context_length
                })
                
            except Exception as e:
                logging.error(f"Error processing text model {handle}: {e}")
                # Still include the model with basic info
                models_info['text'].append({
                    "handle": handle,
                    "display_name": handle,
                    "description": "",
                    "context_length": "32K"  # Default
                })
                continue

        # Process image models
        for handle in image_models:
            try:
                display_name = handle
                description = ""
                try:
                    bot_info = self.poe_client.get_botInfo(handle=handle)
                    if bot_info:
                        display_name = bot_info.get('displayName', handle)
                        description = bot_info.get('description', '')
                except Exception as e:
                    logging.warning(f"Could not get additional info for image model {handle}: {e}")

                models_info['image'].append({
                    "handle": handle,
                    "display_name": display_name,
                    "description": description
                })
            except Exception as e:
                logging.error(f"Error processing image model {handle}: {e}")
                models_info['image'].append({
                    "handle": handle,
                    "display_name": handle,
                    "description": ""
                })

        # Process video models
        for handle in video_models:
            try:
                display_name = handle
                description = ""
                try:
                    bot_info = self.poe_client.get_botInfo(handle=handle)
                    if bot_info:
                        display_name = bot_info.get('displayName', handle)
                        description = bot_info.get('description', '')
                except Exception as e:
                    logging.warning(f"Could not get additional info for video model {handle}: {e}")

                models_info['video'].append({
                    "handle": handle,
                    "display_name": display_name,
                    "description": description
                })
            except Exception as e:
                logging.error(f"Error processing video model {handle}: {e}")
                models_info['video'].append({
                    "handle": handle,
                    "display_name": handle,
                    "description": ""
                })
                
        return models_info

    def setup_commands(self):
        @self.bot.event
        async def on_ready():
            logging.info(f'Logged in as {self.bot.user} (ID: {self.bot.user.id})')
            try:
                # First, remove all global commands
                self.tree.clear_commands(guild=None)
                await self.tree.sync()
                logging.info("Cleared all global commands")
                
                # Then sync guild-specific commands
                for guild_id in self.guild_ids:
                    guild = discord.Object(id=guild_id)
                    synced = await self.tree.sync(guild=guild)
                    logging.info(f'Synced {len(synced)} command(s) for guild {guild_id}')
            except Exception as e:
                logging.error(f'Error syncing commands: {e}')

        # For each command, update the guild parameter to use a list of guilds
        def guild_command(name: str, description: str):
            """Decorator to create a command for multiple guilds"""
            def decorator(func):
                # Register the command for each guild
                for guild_id in self.guild_ids:
                    self.tree.command(
                        name=name,
                        description=description,
                        guild=discord.Object(id=guild_id)
                    )(func)
                return func
            return decorator

        @guild_command(
            name="askpoe",
            description="Send a prompt to Poe.com and receive a private reply"
        )
        async def askpoe(
            interaction: discord.Interaction,
            prompt: str,
            file: discord.Attachment = None
        ):
            await self.handle_askpoe(interaction, prompt, file)

        @guild_command(
            name="llm-list",
            description="List all available LLM models"
        )
        async def llm_list(interaction: discord.Interaction):
            await self.handle_llm_list(interaction)

        @guild_command(
            name="llm-set",
            description="Set your preferred LLM model"
        )
        async def llm_set(interaction: discord.Interaction, model: str):
            await self.handle_llm_set(interaction, model)

        @guild_command(
            name="reset",
            description="Reset your conversation thread"
        )
        async def reset(interaction: discord.Interaction):
            await self.handle_reset(interaction)

        @guild_command(
            name="clear",
            description="Clear current model's chat history and delete it from server"
        )
        async def clear(interaction: discord.Interaction):
            await self.handle_clear(interaction)

        @guild_command(
            name="info",
            description="Display your Poe API settings and current model information"
        )
        async def info(interaction: discord.Interaction):
            await self.handle_info(interaction)

        @guild_command(
            name="suggest",
            description="Get suggestions for your prompt"
        )
        async def suggest(interaction: discord.Interaction, prompt: str):
            await self.handle_suggest(interaction, prompt)

        @guild_command(
            name="share",
            description="Share your conversation thread"
        )
        async def share(interaction: discord.Interaction):
            await self.handle_share(interaction)

        @guild_command(
            name="import",
            description="Import a shared conversation thread"
        )
        async def import_chat(interaction: discord.Interaction, code: str):
            await self.handle_import(interaction, code)

        @guild_command(
            name="citations",
            description="Get citations for a specific message"
        )
        async def citations(interaction: discord.Interaction, message_id: str):
            await self.handle_citations(interaction, message_id)

        @guild_command(
            name="retry",
            description="Retry the last message"
        )
        async def retry(interaction: discord.Interaction):
            await self.handle_retry(interaction)

        @guild_command(
            name="stop",
            description="Stop the current message generation"
        )
        async def stop(interaction: discord.Interaction):
            await self.handle_stop(interaction)

        @guild_command(
            name="purge",
            description="Delete all chat histories for all models from both local storage and server"
        )
        async def purge(interaction: discord.Interaction):
            await self.handle_purge(interaction)

        @guild_command(
            name="admin-purge",
            description="[ADMIN] Purge all chat histories for all users (requires admin password)"
        )
        async def admin_purge(interaction: discord.Interaction, password: str):
            await self.handle_admin_purge(interaction, password)

        @guild_command(
            name="history",
            description="Show your recent conversation history with current model"
        )
        async def history(interaction: discord.Interaction, count: int = 10):
            await self.handle_history(interaction, count)

        @guild_command(
            name="history-all",
            description="Show your recent conversation history with all models"
        )
        async def history_all(interaction: discord.Interaction, count: int = 5):
            await self.handle_history_all(interaction, count)

        @guild_command(
            name="fetch",
            description="Fetch all available models and their info"
        )
        async def fetch(interaction: discord.Interaction, password: str):
            await self.handle_fetch(interaction, password)

        @guild_command(
            name="imagegen-list",
            description="List all available image generation models"
        )
        async def imagegen_list(interaction: discord.Interaction):
            await self.handle_imagegen_list(interaction)

        @guild_command(
            name="videogen-list",
            description="List all available video generation models"
        )
        async def videogen_list(interaction: discord.Interaction):
            await self.handle_videogen_list(interaction)

        @guild_command(
            name="imagegen-set",
            description="Set your preferred image generation model"
        )
        async def imagegen_set(interaction: discord.Interaction, model: str):
            await self.handle_imagegen_set(interaction, model)

        @guild_command(
            name="videogen-set",
            description="Set your preferred video generation model"
        )
        async def videogen_set(interaction: discord.Interaction, model: str):
            await self.handle_videogen_set(interaction, model)

        @guild_command(
            name="help",
            description="Show all available commands and their descriptions"
        )
        async def help(interaction: discord.Interaction):
            help_text = """
**🤖 Poe Discord Bot Commands**

*Chat Commands:*
`/askpoe [prompt]` - Send a prompt to Poe.com and receive a private reply (supports file attachments)
`/suggest [prompt]` - Get suggestions for your prompt

*Model Management:*
`/llm-list` - List all available LLM models
`/llm-set [model]` - Set your preferred LLM model
`/imagegen-list` - List all available image generation models
`/imagegen-set [model]` - Set your preferred image generation model
`/videogen-list` - List all available video generation models
`/videogen-set [model]` - Set your preferred video generation model

*Context Management:*
`/reset` - Reset your conversation thread
`/clear` - Clear current model's chat history and delete it from server
`/purge` - Delete all chat histories for all models from both local storage and server

*History Commands:*
`/history [count]` - Show your recent conversation history with current model (default: last 10 exchanges)
`/history-all [count]` - Show your recent conversation history with all models (default: last 5 exchanges per model)

*Information:*
`/info` - Display your Poe API settings and current model information
`/help` - Show this help message

*Conversation Sharing:*
`/share` - Share your conversation thread
`/import [code]` - Import a shared conversation thread

*Advanced Features:*
`/citations [message_id]` - Get citations for a specific message
`/retry` - Retry the last message
`/stop` - Stop the current message generation

*Admin Commands:*
`/admin-purge [password]` - [ADMIN] Purge all chat histories for all users (requires admin password)
`/fetch [password]` - [ADMIN] Fetch and cache all available models (requires admin password)
"""
            await interaction.response.send_message(help_text, ephemeral=True)

    async def handle_askpoe(self, interaction: discord.Interaction, prompt: str, file: discord.Attachment = None):
        await interaction.response.send_message("⚙️ Processing your request...", ephemeral=True)
        user_id = str(interaction.user.id)
        settings = self.get_user_settings(user_id)

        try:
            file_path = None
            if file:  # Only process file if one was provided
                # Check if file type is supported
                supported_extensions = {
                    # Text files
                    '.pdf', '.docx', '.txt', '.md', '.py', '.js', '.ts', '.html', 
                    '.css', '.csv', '.c', '.cs', '.cpp', '.lua', '.rs', '.rb', 
                    '.go', '.java',
                    # Media files
                    '.png', '.jpg', '.jpeg', '.gif', '.mp4', '.mov', '.mp3', '.wav'
                }
                
                file_ext = os.path.splitext(file.filename)[1].lower()
                if file_ext not in supported_extensions:
                    await interaction.followup.send(
                        "❌ Unsupported file type. Please check the supported file types.",
                        ephemeral=True
                    )
                    return

                try:
                    # Download and save the file temporarily
                    file_bytes = await file.read()
                    file_path = os.path.join(os.getcwd(), file.filename)
                    with open(file_path, 'wb') as f:
                        f.write(file_bytes)
                    
                    logging.info(f"File saved temporarily at: {file_path}")
                    
                    if not os.path.exists(file_path):
                        raise FileNotFoundError(f"Failed to save file at {file_path}")
                    
                except Exception as e:
                    logging.error(f"Error saving file: {e}")
                    await interaction.followup.send(
                        "❌ Failed to process the uploaded file.",
                        ephemeral=True
                    )
                    return

            try:
                # Send message and get response
                logging.info(f"Sending message to {settings.model} with file: {file_path if file_path else 'None'}")
                
                response = ""
                # If we have a file, use file_path parameter and longer timeout
                try:
                    if file_path:
                        # For file uploads, we need to wait longer
                        await interaction.followup.send("📤 Uploading and processing file... this may take a minute...", ephemeral=True)
                        message_generator = self.poe_client.send_message(
                            bot=settings.model,
                            message=prompt,
                            chatId=settings.get_chat_id(settings.model),
                            file_path=[file_path]
                        )
                    else:
                        message_generator = self.poe_client.send_message(
                            bot=settings.model,
                            message=prompt,
                            chatId=settings.get_chat_id(settings.model)
                        )
                    
                    if message_generator is None:
                        raise Exception("Failed to get response from Poe")
                        
                    async for chunk in self.async_generator(message_generator):
                        if isinstance(chunk, dict):
                            partial_response = chunk.get("response", "")
                            if partial_response:
                                response += partial_response
                            
                            # Update chat ID from the response
                            if chunk.get("chatId"):
                                settings.set_chat_id(settings.model, chunk["chatId"])
                                self.save_user_settings()
                    
                    logging.info(f"Received complete response of length: {len(response)}")
                
                except Exception as e:
                    error_str = str(e)
                    logging.error(f"Error in message processing: {error_str}")
                    
                    if "timeout" in error_str.lower() or "Server Error" in error_str:
                        if file_path:
                            await interaction.followup.send(
                                "⌛ The file is taking longer to process than expected. Please try again or use a smaller file.",
                                ephemeral=True
                            )
                        else:
                            await interaction.followup.send(
                                "⌛ The server is taking longer than expected to respond. Please try again.",
                                ephemeral=True
                            )
                    elif "JSONDecodeError" in error_str:
                        await interaction.followup.send(
                            "❌ Received an invalid response from the server. Please try again.",
                            ephemeral=True
                        )
                    else:
                        await interaction.followup.send(
                            f"❌ An error occurred: {error_str}",
                            ephemeral=True
                        )
                    return
                    
            finally:
                # Clean up temporary file only if it was created
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        logging.info(f"Cleaned up temporary file: {file_path}")
                    except Exception as e:
                        logging.error(f"Error cleaning up file: {e}")

            if response:
                # Store the conversation exchange in history
                history_prompt = prompt
                if file:  # Only add file info if a file was provided
                    history_prompt += f"\n[Attached file: {file.filename}]"
                    
                settings.conversation_history.append({
                    "role": "user",
                    "content": history_prompt,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "model": settings.model
                })
                settings.conversation_history.append({
                    "role": "assistant",
                    "content": response,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "model": settings.model
                })
                self.save_user_settings()

                formatted_message = f"**Your prompt:** {prompt}"
                if file:  # Only add file info if a file was provided
                    formatted_message += f"\n**Attached file:** `{file.filename}`"
                formatted_message += f"\n**{settings.model}:** {response}"
                
                # Split message if too long
                if len(formatted_message) <= 2000:
                    await interaction.followup.send(formatted_message, ephemeral=True)
                else:
                    chunks = [formatted_message[i:i+1990] for i in range(0, len(formatted_message), 1990)]
                    for i, chunk in enumerate(chunks):
                        if i == 0:
                            await interaction.followup.send(chunk, ephemeral=True)
                        else:
                            await interaction.followup.send(f"(continued) {chunk}", ephemeral=True)
            else:
                await interaction.followup.send("❌ No response generated.", ephemeral=True)

        except Exception as e:
            logging.error(f"Error in askpoe: {e}")
            error_message = "❌ An error occurred while processing your request."
            if "Failed to get response from Poe" in str(e):
                error_message = "❌ Failed to get a response from Poe. Please try again."
            elif "'NoneType' object is not iterable" in str(e):
                error_message = "❌ Failed to establish communication with Poe. Please try again."
            await interaction.followup.send(
                error_message,
                ephemeral=True
            )

    async def handle_llm_list(self, interaction: discord.Interaction):
        await interaction.response.send_message("📋 Listing available models...", ephemeral=True)
        try:
            if not self.cached_models:
                await interaction.followup.send(
                    "⚠️ No models cached. Please ask an admin to run the `/fetch` command first.",
                    ephemeral=True
                )
                return
                
            response = "**Available Models:**\n\n"
            for model in self.cached_models:
                response += f"• **{model['display_name']}** (`{model['handle']}`)\n"
                response += f"  Context: {model['context_length']}\n"
                if model['description']:
                    response += f"  Description: {model['description']}\n"
                response += "\n"
            
            # Split message if too long
            if len(response) <= 2000:
                await interaction.followup.send(response, ephemeral=True)
            else:
                chunks = [response[i:i+1990] for i in range(0, len(response), 1990)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await interaction.followup.send(chunk, ephemeral=True)
                    else:
                        await interaction.followup.send(f"(continued)\n{chunk}", ephemeral=True)
                        
        except Exception as e:
            logging.error(f"Error in llm-list: {e}")
            await interaction.followup.send(
                "❌ Failed to list available models.",
                ephemeral=True
            )

    async def handle_llm_set(self, interaction: discord.Interaction, model: str):
        await interaction.response.send_message(f"⚙️ Setting model to {model}...", ephemeral=True)
        try:
            # Convert input to lowercase for case-insensitive comparison
            model = model.lower()
            
            if not self.cached_models:
                await interaction.followup.send(
                    "⚠️ No models cached. Please ask an admin to run the `/fetch` command first.",
                    ephemeral=True
                )
                return

            # Check if the model exists in cached models (by handle or display name)
            valid_model = None
            for cached_model in self.cached_models:
                if (model == cached_model['handle'].lower() or 
                    model == cached_model['display_name'].lower()):
                    valid_model = cached_model['handle']
                    break

            if not valid_model:
                await interaction.followup.send(
                    f"❌ Invalid model. Use `/llm-list` to see available models.",
                    ephemeral=True
                )
                return

            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            
            # Only reset chat if actually changing models
            if settings.model != valid_model:
                settings.model = valid_model
                settings.clear_chat_id(valid_model)
                self.save_user_settings()
                await interaction.followup.send(
                    f"✅ Your model has been set to `{valid_model}` and a new chat session has been started.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"✅ Already using model `{valid_model}`. Chat session maintained.",
                    ephemeral=True
                )
        except Exception as e:
            logging.error(f"Error in llm-set: {e}")
            await interaction.followup.send(
                "❌ Failed to set model.",
                ephemeral=True
            )

    async def handle_reset(self, interaction: discord.Interaction):
        await interaction.response.send_message("🔄 Resetting your chat...", ephemeral=True)
        try:
            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            for model in settings.chat_ids:
                settings.clear_chat_id(model)
            self.save_user_settings()

            await interaction.followup.send(
                "✅ Your chat has been reset.",
                ephemeral=True
            )
        except Exception as e:
            logging.error(f"Error in reset: {e}")
            await interaction.followup.send(
                "❌ Failed to reset chat.",
                ephemeral=True
            )

    async def handle_clear(self, interaction: discord.Interaction):
        await interaction.response.send_message("🧹 Clearing current model's chat history...", ephemeral=True)
        try:
            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            current_model = settings.model
            
            # Get chat ID for current model
            chat_id = settings.get_chat_id(current_model)
            
            if chat_id:
                # Delete the chat on the server side
                try:
                    self.poe_client.delete_chat(current_model, chatId=chat_id)
                    logging.info(f"Deleted chat {chat_id} for model {current_model}")
                except Exception as e:
                    logging.error(f"Error deleting chat on server: {e}")
                    await interaction.followup.send(
                        "⚠️ Failed to delete chat on server, but cleared local history.",
                        ephemeral=True
                    )
            
            # Filter out messages from current model
            settings.conversation_history = [
                msg for msg in settings.conversation_history 
                if msg["model"] != current_model
            ]
            
            # Clear chat ID for current model
            settings.clear_chat_id(current_model)
            self.save_user_settings()
            
            await interaction.followup.send(
                f"✅ Chat history for `{current_model}` has been cleared.",
                ephemeral=True
            )
        except Exception as e:
            logging.error(f"Error in clear: {e}")
            await interaction.followup.send(
                "❌ Failed to clear chat history.",
                ephemeral=True
            )

    async def handle_info(self, interaction: discord.Interaction):
        await interaction.response.send_message("📊 Fetching your information...", ephemeral=True)
        try:
            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            
            # Get account settings
            try:
                poe_settings = self.poe_client.get_settings()
                logging.info(f"Poe settings response: {poe_settings}")  # Log the full response
            except Exception as e:
                logging.error(f"Error getting settings: {e}")
                poe_settings = None
            
            # Get bot info based on model type
            bot_info = None
            model_type = "LLM"
            if any(model['handle'] == settings.model for model in self.cached_image_models):
                model_type = "Image Generation"
            elif any(model['handle'] == settings.model for model in self.cached_video_models):
                model_type = "Video Generation"
            
            try:
                bot_info = self.poe_client.get_botInfo(handle=settings.model)
                logging.info(f"Bot info response: {bot_info}")  # Log the full response
            except Exception as e:
                logging.error(f"Could not get bot info for {settings.model}: {e}")
            
            # Build the info message
            info_message = "**Your Settings:**\n"
            info_message += f"- Current Model: `{settings.model}`\n"
            info_message += f"- Model Type: `{model_type}`\n"
            info_message += f"- Active Chat: `{'Yes' if settings.get_chat_id(settings.model) else 'No'}`\n\n"

            info_message += "**Model Information:**\n"
            if bot_info:
                info_message += f"- Display Name: `{bot_info.get('displayName', settings.model)}`\n"
                if 'description' in bot_info and bot_info['description']:
                    info_message += f"- Description: `{bot_info['description']}`\n"
                if 'messageTimeoutSecs' in bot_info:
                    info_message += f"- Message Timeout: `{bot_info['messageTimeoutSecs']} seconds`\n"
                if 'displayMessagePointPrice' in bot_info:
                    info_message += f"- Point Cost: `{bot_info['displayMessagePointPrice']} points per message`\n"
                if 'supportsFileUpload' in bot_info:
                    info_message += f"- File Upload Support: `{'Yes' if bot_info['supportsFileUpload'] else 'No'}`\n"
            else:
                info_message += "- No detailed model information available\n"
            
            info_message += "\n**Account Information:**\n"
            if poe_settings:
                # Check for subscription status
                if 'hasSubscription' in poe_settings:
                    subscription_status = "Premium" if poe_settings['hasSubscription'] else "Free"
                    info_message += f"- Subscription Status: `{subscription_status}`\n"
                if 'subscriptionPlan' in poe_settings:
                    info_message += f"- Subscription Plan: `{poe_settings['subscriptionPlan']}`\n"
                if 'messagePointBalance' in poe_settings:
                    info_message += f"- Point Balance: `{poe_settings['messagePointBalance']} points`\n"
                if 'messageLimit' in poe_settings:
                    info_message += f"- Message Limit: `{poe_settings['messageLimit']}`\n"
                if 'numRemainingMessages' in poe_settings:
                    info_message += f"- Remaining Messages: `{poe_settings['numRemainingMessages']}`\n"
                if 'dailyMessageLimit' in poe_settings:
                    info_message += f"- Daily Message Limit: `{poe_settings['dailyMessageLimit']}`\n"
                if 'dailyMessagesRemaining' in poe_settings:
                    info_message += f"- Daily Messages Remaining: `{poe_settings['dailyMessagesRemaining']}`\n"
            else:
                info_message += "- Could not fetch account information\n"

            await interaction.followup.send(info_message, ephemeral=True)
        except Exception as e:
            logging.error(f"Error in info: {e}")
            await interaction.followup.send(
                "❌ Failed to fetch information.",
                ephemeral=True
            )

    async def handle_suggest(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.send_message("💭 Getting suggestions...", ephemeral=True)
        try:
            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            
            suggestions = self.poe_client.get_suggestions(
                settings.model,
                prompt,
                chatId=settings.get_chat_id(settings.model)
            )
            
            if suggestions:
                suggestion_text = "**Suggestions for your prompt:**\n"
                for i, suggestion in enumerate(suggestions, 1):
                    suggestion_text += f"{i}. {suggestion}\n"
                await interaction.followup.send(suggestion_text, ephemeral=True)
            else:
                await interaction.followup.send(
                    "ℹ️ No suggestions available for this prompt.",
                    ephemeral=True
                )
        except Exception as e:
            logging.error(f"Error in suggest: {e}")
            await interaction.followup.send(
                "❌ Failed to get suggestions.",
                ephemeral=True
            )

    @staticmethod
    def async_generator(gen):
        """Convert a synchronous generator to an async generator."""
        async def wrapper():
            for item in gen:
                yield item
                await asyncio.sleep(0)
        return wrapper()

    async def handle_share(self, interaction: discord.Interaction):
        await interaction.response.send_message("🔗 Generating share code...", ephemeral=True)
        try:
            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            
            if not settings.get_chat_id(settings.model):
                await interaction.followup.send("❌ No active chat to share.", ephemeral=True)
                return
            
            share_code = self.poe_client.share_chat(settings.model, chatId=settings.get_chat_id(settings.model))
            await interaction.followup.send(f"✅ Share Code: `{share_code}`", ephemeral=True)
        except Exception as e:
            logging.error(f"Error in share: {e}")
            await interaction.followup.send("❌ Failed to generate share code.", ephemeral=True)

    async def handle_import(self, interaction: discord.Interaction, code: str):
        await interaction.response.send_message("📥 Importing chat...", ephemeral=True)
        try:
            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            
            result = self.poe_client.import_chat(settings.model, code)
            chat_id = result.get('chatId')
            if not chat_id:
                await interaction.followup.send("❌ Failed to import chat: No chat ID received.", ephemeral=True)
                return
                
            settings.set_chat_id(settings.model, chat_id)
            self.save_user_settings()
            
            # Fetch the imported chat history
            try:
                messages = self.poe_client.get_message_history(settings.model, chat_id)
                if messages:
                    formatted_history = "**📥 Imported Chat History:**\n\n"
                    for msg in messages:
                        role = "👤 **You:**" if msg.get('role') == 'user' else "🤖 **Assistant:**"
                        formatted_history += f"{role} {msg.get('text', '')}\n\n"
                        
                    # Split into chunks if needed
                    if len(formatted_history) <= 2000:
                        await interaction.followup.send(formatted_history, ephemeral=True)
                    else:
                        chunks = [formatted_history[i:i+1990] for i in range(0, len(formatted_history), 1990)]
                        for i, chunk in enumerate(chunks):
                            if i == 0:
                                await interaction.followup.send(chunk, ephemeral=True)
                            else:
                                await interaction.followup.send(f"(continued)\n{chunk}", ephemeral=True)
                else:
                    await interaction.followup.send("✅ Chat imported successfully, but no message history found.", ephemeral=True)
            except Exception as e:
                logging.error(f"Error fetching imported chat history: {e}")
                await interaction.followup.send("✅ Chat imported successfully, but failed to fetch message history.", ephemeral=True)
                
        except Exception as e:
            logging.error(f"Error in import: {e}")
            await interaction.followup.send("❌ Failed to import chat.", ephemeral=True)

    async def handle_citations(self, interaction: discord.Interaction, message_id: str):
        await interaction.response.send_message("📚 Fetching citations...", ephemeral=True)
        try:
            citations = self.poe_client.get_citations(message_id)
            if citations:
                await interaction.followup.send(f"📖 Citations:\n{citations}", ephemeral=True)
            else:
                await interaction.followup.send("ℹ️ No citations found.", ephemeral=True)
        except Exception as e:
            logging.error(f"Error in citations: {e}")
            await interaction.followup.send("❌ Failed to fetch citations.", ephemeral=True)

    async def handle_retry(self, interaction: discord.Interaction):
        await interaction.response.send_message("🔄 Retrying last message...", ephemeral=True)
        try:
            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            
            if not settings.get_chat_id(settings.model):
                await interaction.followup.send("❌ No message to retry.", ephemeral=True)
                return
            
            response = ""
            try:
                message_generator = self.poe_client.retry_message(settings.get_chat_id(settings.model))
                if message_generator is None:
                    raise Exception("Failed to get response from Poe")
                    
                async for chunk in self.async_generator(message_generator):
                    if isinstance(chunk, dict):
                        partial_response = chunk.get("response", "")
                        if partial_response:
                            response += str(partial_response)
                
                if response:
                    # Store the retry in conversation history
                    settings.conversation_history.append({
                        "role": "assistant",
                        "content": response,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "model": settings.model
                    })
                    self.save_user_settings()
                    
                    # Split message if too long
                    if len(response) <= 2000:
                        await interaction.followup.send(f"🔄 Retry response:\n{response}", ephemeral=True)
                    else:
                        chunks = [response[i:i+1990] for i in range(0, len(response), 1990)]
                        for i, chunk in enumerate(chunks):
                            if i == 0:
                                await interaction.followup.send(f"🔄 Retry response:\n{chunk}", ephemeral=True)
                            else:
                                await interaction.followup.send(f"(continued)\n{chunk}", ephemeral=True)
                else:
                    await interaction.followup.send("❌ No response generated.", ephemeral=True)
                    
            except Exception as e:
                error_str = str(e)
                logging.error(f"Error in retry message processing: {error_str}")
                
                if "timeout" in error_str.lower():
                    await interaction.followup.send(
                        "⌛ The server is taking longer than expected to respond. Please try again.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"❌ An error occurred while retrying: {error_str}",
                        ephemeral=True
                    )
                return
                
        except Exception as e:
            logging.error(f"Error in retry: {e}")
            await interaction.followup.send("❌ Failed to retry message.", ephemeral=True)

    async def handle_stop(self, interaction: discord.Interaction):
        await interaction.response.send_message("🛑 Stopping message generation...", ephemeral=True)
        try:
            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            
            if settings.get_chat_id(settings.model):
                self.poe_client.cancel_message(settings.get_chat_id(settings.model))
                await interaction.followup.send("✅ Message generation stopped.", ephemeral=True)
            else:
                await interaction.followup.send("ℹ️ No active message generation.", ephemeral=True)
        except Exception as e:
            logging.error(f"Error in stop: {e}")
            await interaction.followup.send("❌ Failed to stop message generation.", ephemeral=True)

    async def handle_purge(self, interaction: discord.Interaction):
        await interaction.response.send_message("🗑️ Purging all chat history...", ephemeral=True)
        try:
            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            
            # Delete all server-side chats
            failed_deletions = []
            for model, chat_id in settings.chat_ids.items():
                if chat_id:
                    try:
                        self.poe_client.delete_chat(model, chatId=chat_id)
                        logging.info(f"Deleted chat {chat_id} for model {model}")
                    except Exception as e:
                        logging.error(f"Error deleting chat for model {model}: {e}")
                        failed_deletions.append(model)
            
            # Clear all conversation history
            settings.conversation_history = []
            
            # Clear all chat IDs
            for model in list(settings.chat_ids.keys()):
                settings.clear_chat_id(model)
            
            self.save_user_settings()
            
            if failed_deletions:
                await interaction.followup.send(
                    f"⚠️ Cleared all history but failed to delete some chats on server for models: {', '.join(failed_deletions)}",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "✅ All chat history has been purged.",
                    ephemeral=True
                )
        except Exception as e:
            logging.error(f"Error in purge: {e}")
            await interaction.followup.send(
                "❌ Failed to purge chat history.",
                ephemeral=True
            )

    async def handle_admin_purge(self, interaction: discord.Interaction, password: str):
        """Handle admin purge command with password protection"""
        # Immediately delete the message to hide the password
        await interaction.response.send_message("🔒 Verifying credentials...", ephemeral=True)
        
        if not self.admin_password:
            await interaction.followup.send(
                "❌ Admin purge is disabled: ADMIN_PASSWORD not configured.",
                ephemeral=True
            )
            return
            
        if password != self.admin_password:
            await interaction.followup.send(
                "❌ Invalid admin password.",
                ephemeral=True
            )
            return
            
        try:
            await interaction.followup.send("⚠️ Starting global purge of all user chats...", ephemeral=True)
            
            # Track statistics
            total_users = len(self.user_settings)
            processed_users = 0
            failed_deletions = []
            
            # Iterate through all users
            for user_id, settings in self.user_settings.items():
                processed_users += 1
                await interaction.followup.send(
                    f"📊 Progress: Processing user {processed_users}/{total_users}...",
                    ephemeral=True
                )
                
                # Delete all server-side chats for this user
                for model, chat_id in settings.chat_ids.items():
                    if chat_id:
                        try:
                            self.poe_client.delete_chat(model, chatId=chat_id)
                            logging.info(f"Deleted chat {chat_id} for model {model} (user: {user_id})")
                        except Exception as e:
                            logging.error(f"Error deleting chat for user {user_id}, model {model}: {e}")
                            failed_deletions.append(f"User {user_id}, Model {model}")
                
                # Clear user's conversation history and chat IDs
                settings.conversation_history = []
                for model in list(settings.chat_ids.keys()):
                    settings.clear_chat_id(model)
            
            # Save the cleared settings
            self.save_user_settings()
            
            # Send summary
            summary = f"""
✅ **Admin Purge Complete**
- Total Users Processed: {total_users}
- Users Cleared: {total_users}
"""
            if failed_deletions:
                summary += f"\n⚠️ **Failed Deletions:**\n"
                for failure in failed_deletions[:10]:  # Show first 10 failures
                    summary += f"- {failure}\n"
                if len(failed_deletions) > 10:
                    summary += f"- ... and {len(failed_deletions) - 10} more\n"
            
            await interaction.followup.send(summary, ephemeral=True)
            
        except Exception as e:
            logging.error(f"Error in admin purge: {e}")
            await interaction.followup.send(
                "❌ An error occurred during admin purge. Check logs for details.",
                ephemeral=True
            )

    async def handle_history(self, interaction: discord.Interaction, count: int = 10):
        """Show conversation history with current model"""
        await interaction.response.send_message("📜 Fetching conversation history...", ephemeral=True)
        try:
            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            
            if not settings.conversation_history:
                await interaction.followup.send("No conversation history found.", ephemeral=True)
                return

            # Filter history for current model
            current_model_history = [
                msg for msg in settings.conversation_history 
                if msg["model"] == settings.model
            ]

            if not current_model_history:
                await interaction.followup.send(
                    f"No conversation history found for model `{settings.model}`.", 
                    ephemeral=True
                )
                return

            # Get the last 'count' exchanges (pairs of messages)
            history = current_model_history[-count*2:]  # Multiply by 2 to get pairs
            
            formatted_history = f"**Conversation History for {settings.model}:**\n\n"
            for msg in history:
                timestamp = msg["timestamp"]
                if msg["role"] == "user":
                    formatted_history += f"🕒 `{timestamp}`\n👤 **You:** {msg['content']}\n\n"
                else:
                    formatted_history += f"🤖 **Response:** {msg['content']}\n\n"

            # Split into chunks of ~1900 characters (leaving room for formatting)
            chunks = []
            current_chunk = ""
            
            for line in formatted_history.split('\n'):
                if len(current_chunk) + len(line) + 2 > 1900:  # +2 for newlines
                    chunks.append(current_chunk)
                    current_chunk = line
                else:
                    current_chunk += line + '\n'
            
            if current_chunk:
                chunks.append(current_chunk)

            # Send chunks as separate messages
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await interaction.followup.send(
                        f"{chunk}\n*(Message {i+1}/{len(chunks)})*", 
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"*(Continued - {i+1}/{len(chunks)})*\n\n{chunk}", 
                        ephemeral=True
                    )
                # Add a small delay between messages to prevent rate limiting
                await asyncio.sleep(0.5)

        except Exception as e:
            logging.error(f"Error in history: {e}")
            await interaction.followup.send(
                "❌ Failed to fetch conversation history.",
                ephemeral=True
            )

    async def handle_history_all(self, interaction: discord.Interaction, count: int = 5):
        """Show conversation history with all models"""
        await interaction.response.send_message("📚 Fetching all conversation histories...", ephemeral=True)
        try:
            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            
            if not settings.conversation_history:
                await interaction.followup.send("No conversation history found.", ephemeral=True)
                return

            # Group history by model
            history_by_model = {}
            for msg in settings.conversation_history:
                model = msg["model"]
                if model not in history_by_model:
                    history_by_model[model] = []
                history_by_model[model].append(msg)

            if not history_by_model:
                await interaction.followup.send("No conversation history found.", ephemeral=True)
                return

            # Format history for each model
            formatted_history = "**📚 All Conversation Histories**\n\n"
            for model, messages in history_by_model.items():
                # Get the last 'count' exchanges (pairs of messages)
                recent_messages = messages[-count*2:]  # Multiply by 2 to get pairs
                
                formatted_history += f"**Model: `{model}`**\n"
                formatted_history += f"{'='*40}\n"
                
                for msg in recent_messages:
                    timestamp = msg["timestamp"]
                    if msg["role"] == "user":
                        formatted_history += f"🕒 `{timestamp}`\n👤 **You:** {msg['content']}\n\n"
                    else:
                        formatted_history += f"🤖 **Response:** {msg['content']}\n\n"
                
                formatted_history += f"{'='*40}\n\n"

            # Split into chunks of ~1900 characters
            chunks = []
            current_chunk = ""
            
            for line in formatted_history.split('\n'):
                if len(current_chunk) + len(line) + 2 > 1900:
                    chunks.append(current_chunk)
                    current_chunk = line
                else:
                    current_chunk += line + '\n'
            
            if current_chunk:
                chunks.append(current_chunk)

            # Send chunks as separate messages
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await interaction.followup.send(
                        f"{chunk}\n*(Page {i+1}/{len(chunks)})*", 
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"*(Page {i+1}/{len(chunks)})*\n\n{chunk}", 
                        ephemeral=True
                    )
                # Add a small delay between messages to prevent rate limiting
                await asyncio.sleep(0.5)

        except Exception as e:
            logging.error(f"Error in history-all: {e}")
            await interaction.followup.send(
                "❌ Failed to fetch conversation histories.",
                ephemeral=True
            )

    async def handle_fetch(self, interaction: discord.Interaction, password: str):
        """Handle fetch command with password protection"""
        await interaction.response.send_message("🔒 Verifying credentials...", ephemeral=True)
        
        if not self.admin_password:
            await interaction.followup.send(
                "❌ Fetch is disabled: ADMIN_PASSWORD not configured.",
                ephemeral=True
            )
            return
            
        if password != self.admin_password:
            await interaction.followup.send(
                "❌ Invalid admin password.",
                ephemeral=True
            )
            return
            
        try:
            await interaction.followup.send("🔄 Fetching all available models... This may take a minute...", ephemeral=True)
            
            # Fetch all models
            models_info = await self.fetch_all_models()
            
            # Update cache
            self.cached_models = models_info['text']
            self.cached_image_models = models_info['image']
            self.cached_video_models = models_info['video']
            self.save_models_cache()
            
            await interaction.followup.send(
                f"✅ Successfully cached {len(models_info['text'])} text models and {len(models_info['image'])} image models and {len(models_info['video'])} video models. Users can now use `/llm-list` to view them.",
                ephemeral=True
            )
            
        except Exception as e:
            logging.error(f"Error in fetch: {e}")
            await interaction.followup.send(
                "❌ An error occurred while fetching models. Check logs for details.",
                ephemeral=True
            )

    async def handle_imagegen_list(self, interaction: discord.Interaction):
        await interaction.response.send_message("📋 Listing available image generation models...", ephemeral=True)
        try:
            if not self.cached_image_models:
                await interaction.followup.send(
                    "⚠️ No image models cached. Please ask an admin to run the `/fetch` command first.",
                    ephemeral=True
                )
                return
                
            response = "**Available Image Generation Models:**\n\n"
            for model in self.cached_image_models:
                response += f"• **{model['display_name']}** (`{model['handle']}`)\n"
                if model['description']:
                    response += f"  Description: {model['description']}\n"
                response += "\n"
            
            # Split message if too long
            if len(response) <= 2000:
                await interaction.followup.send(response, ephemeral=True)
            else:
                chunks = [response[i:i+1990] for i in range(0, len(response), 1990)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await interaction.followup.send(chunk, ephemeral=True)
                    else:
                        await interaction.followup.send(f"(continued)\n{chunk}", ephemeral=True)
                        
        except Exception as e:
            logging.error(f"Error in imagegen-list: {e}")
            await interaction.followup.send(
                "❌ Failed to list available image generation models.",
                ephemeral=True
            )

    async def handle_videogen_list(self, interaction: discord.Interaction):
        await interaction.response.send_message("📋 Listing available video generation models...", ephemeral=True)
        try:
            if not self.cached_video_models:
                await interaction.followup.send(
                    "⚠️ No video models cached. Please ask an admin to run the `/fetch` command first.",
                    ephemeral=True
                )
                return
                
            response = "**Available Video Generation Models:**\n\n"
            for model in self.cached_video_models:
                response += f"• **{model['display_name']}** (`{model['handle']}`)\n"
                if model['description']:
                    response += f"  Description: {model['description']}\n"
                response += "\n"
            
            # Split message if too long
            if len(response) <= 2000:
                await interaction.followup.send(response, ephemeral=True)
            else:
                chunks = [response[i:i+1990] for i in range(0, len(response), 1990)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await interaction.followup.send(chunk, ephemeral=True)
                    else:
                        await interaction.followup.send(f"(continued)\n{chunk}", ephemeral=True)
                        
        except Exception as e:
            logging.error(f"Error in videogen-list: {e}")
            await interaction.followup.send(
                "❌ Failed to list available video generation models.",
                ephemeral=True
            )

    async def handle_imagegen_set(self, interaction: discord.Interaction, model: str):
        await interaction.response.send_message(f"⚙️ Setting image generation model to {model}...", ephemeral=True)
        try:
            # Convert input to lowercase for case-insensitive comparison
            model = model.lower()
            
            if not self.cached_image_models:
                await interaction.followup.send(
                    "⚠️ No image models cached. Please ask an admin to run the `/fetch` command first.",
                    ephemeral=True
                )
                return

            # Check if the model exists in cached models (by handle or display name)
            valid_model = None
            for cached_model in self.cached_image_models:
                if (model == cached_model['handle'].lower() or 
                    model == cached_model['display_name'].lower()):
                    valid_model = cached_model['handle']
                    break

            if not valid_model:
                await interaction.followup.send(
                    f"❌ Invalid model. Use `/imagegen-list` to see available models.",
                    ephemeral=True
                )
                return

            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            
            # Only reset chat if actually changing models
            if settings.model != valid_model:
                settings.model = valid_model
                settings.clear_chat_id(valid_model)
                self.save_user_settings()
                await interaction.followup.send(
                    f"✅ Your image generation model has been set to `{valid_model}` and a new chat session has been started.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"✅ Already using model `{valid_model}`. Chat session maintained.",
                    ephemeral=True
                )
        except Exception as e:
            logging.error(f"Error in imagegen-set: {e}")
            await interaction.followup.send(
                "❌ Failed to set image generation model.",
                ephemeral=True
            )

    async def handle_videogen_set(self, interaction: discord.Interaction, model: str):
        await interaction.response.send_message(f"⚙️ Setting video generation model to {model}...", ephemeral=True)
        try:
            # Convert input to lowercase for case-insensitive comparison
            model = model.lower()
            
            if not self.cached_video_models:
                await interaction.followup.send(
                    "⚠️ No video models cached. Please ask an admin to run the `/fetch` command first.",
                    ephemeral=True
                )
                return

            # Check if the model exists in cached models (by handle or display name)
            valid_model = None
            for cached_model in self.cached_video_models:
                if (model == cached_model['handle'].lower() or 
                    model == cached_model['display_name'].lower()):
                    valid_model = cached_model['handle']
                    break

            if not valid_model:
                await interaction.followup.send(
                    f"❌ Invalid model. Use `/videogen-list` to see available models.",
                    ephemeral=True
                )
                return

            user_id = str(interaction.user.id)
            settings = self.get_user_settings(user_id)
            
            # Only reset chat if actually changing models
            if settings.model != valid_model:
                settings.model = valid_model
                settings.clear_chat_id(valid_model)
                self.save_user_settings()
                await interaction.followup.send(
                    f"✅ Your video generation model has been set to `{valid_model}` and a new chat session has been started.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"✅ Already using model `{valid_model}`. Chat session maintained.",
                    ephemeral=True
                )
        except Exception as e:
            logging.error(f"Error in videogen-set: {e}")
            await interaction.followup.send(
                "❌ Failed to set video generation model.",
                ephemeral=True
            )

    def run(self):
        """Run the Discord bot"""
        self.bot.run(self.discord_token)

if __name__ == "__main__":
    bot = PoeDiscordBot()
    bot.run() 