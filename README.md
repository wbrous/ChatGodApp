# Twitch Chat TTS Application

This application combines a Twitch bot with a web interface to allow you to select specific chatters and have their messages read aloud using Text-to-Speech (TTS).

## Features

- Web interface with 3 user slots
- Text-to-Speech for selected chatters
- Random user selection from active chatters
- Manual user selection

## Setup

1. Create a `.env` file in the root directory using the `.env.example` as a template:
```
# Twitch credentials
TWITCH_ACCESS_TOKEN=your_twitch_oauth_token_here
TWITCH_CHANNEL=your_twitch_channel_name_here

# Amazon Polly credentials
AWS_ENABLED=1 # 1 to enable, 0 to disable
AWS_REGION=us-east-1  # Change to your preferred AWS region
AWS_ACCESS_KEY_ID=your_aws_access_key_id_here
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key_here

# Flask secret key (change this to something random)
SECRET_KEY=your_secret_key_here
```

You can get a Twitch access token by:
- Going to https://twitchapps.com/tmi/ and connecting with your Twitch account
- The token should start with "oauth:"

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
python web_app.py
```

4. Open your browser and navigate to `http://localhost:5000`

## How to Use

1. Have users type one of the following commands in your Twitch chat to register:
   - `!player1` - Register for slot 1
   - `!player2` - Register for slot 2
   - `!player3` - Register for slot 3

2. In the web interface:
   - Click "Pick Random" to select a random registered user for a slot
   - Or enter a specific username in "Choose User"
   - Toggle TTS on/off using the checkboxes
   
3. When a selected user chats, their message will appear in the web interface and be read aloud.
