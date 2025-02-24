<div align="center">
<h1>POE Discord Bot 🤖</h1>
<p><em>A powerful Discord bot that integrates with Poe.com's AI models for text, image, and video generation</em></p>
</div>

<p align="center">
<img alt="Python Version" src="https://img.shields.io/badge/python-3.7+-blue.svg">
<img alt="Discord.py Version" src="https://img.shields.io/badge/discord.py-2.0+-blue.svg">
<img alt="License" src="https://img.shields.io/badge/license-MIT-green.svg">
</p>

## 📚 Features

### AI Model Support
- **Text Generation (LLMs)**
  - Access to various LLM models including GPT-4, Claude-3, and more
  - Context-aware conversations with history tracking
  - File upload support for document analysis
  
- **Image Generation**
  - Support for multiple image generation models
  - High-quality image creation from text prompts
  
- **Video Generation**
  - Access to video generation capabilities
  - Create videos from text descriptions

### Command System
- **Model Management**
  - `/llm-list` - List all available LLM models
  - `/llm-set` - Set your preferred LLM model
  - `/imagegen-list` - List available image generation models
  - `/imagegen-set` - Set preferred image generation model
  - `/videogen-list` - List available video generation models
  - `/videogen-set` - Set preferred video generation model

- **Chat Commands**
  - `/askpoe` - Send prompts and receive AI responses
  - `/suggest` - Get suggestions for your prompt
  - `/retry` - Retry the last message
  - `/stop` - Stop ongoing message generation

- **Context Management**
  - `/reset` - Reset your conversation thread
  - `/clear` - Clear current model's chat history
  - `/purge` - Delete all chat histories
  - `/history` - View recent conversation history
  - `/history-all` - View history across all models

- **Information & Utilities**
  - `/info` - Display settings and model information
  - `/share` - Share conversation threads
  - `/import` - Import shared conversations
  - `/citations` - Get citations for responses
  - `/help` - Show all available commands

## 🚀 Setup

### Prerequisites
- Python 3.7+
- Discord Bot Token
- Poe.com API Tokens (p-b and p-lat)

### Installation

1. Clone the repository:
```bash
git clone [your-repository-url]
cd [repository-name]
```

2. Install required packages:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with the following configuration:
```env
DISCORD_TOKEN="your-discord-bot-token"
GUILD_IDS="guild-id-1,guild-id-2"  # Comma-separated list of guild IDs
POE_PB="your-poe-pb-token"
POE_PLAT="your-poe-plat-token"
ADMIN_PASSWORD="your-admin-password"  # For admin commands
```

4. Run the bot:
```bash
python bot.py
```

## 💡 Usage

### Basic Commands
1. Start by setting your preferred model:
```
/llm-set gpt-4
```

2. Send a prompt to the AI:
```
/askpoe What is quantum computing?
```

3. View your conversation history:
```
/history
```

### Working with Files
The bot supports various file types for analysis:
- Documents: PDF, DOCX, TXT, MD
- Code: PY, JS, TS, HTML, CSS, etc.
- Media: PNG, JPG, GIF, MP4, etc.

To use a file:
```
/askpoe Analyze this code [attach file]
```

### Managing Conversations
- Use `/reset` to start fresh
- Use `/clear` to remove current model's history
- Use `/share` to get a shareable conversation code
- Use `/import [code]` to import shared conversations

## 🔧 Configuration

### Guild-Specific Commands
The bot supports multiple Discord servers (guilds). Add guild IDs to the `GUILD_IDS` environment variable as a comma-separated list.

### Admin Commands
- `/admin-purge` - Purge all user chat histories (requires admin password)
- `/fetch` - Update available models cache (requires admin password)

## 📝 License
[MIT License]

## 🤝 Contributing
Contributions are welcome! Please feel free to submit a Pull Request.
