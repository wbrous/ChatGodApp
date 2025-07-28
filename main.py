#!/usr/bin/env python3
"""
Twitch Chat TTS Bot with Web Interface
"""

import os
import sys
import signal
import asyncio
import threading
import time
import random
import requests as http_requests
import json
from datetime import datetime, timedelta
import pytz
import dotenv

from flask import Flask, render_template, session, request
from flask_socketio import SocketIO, emit
from twitchio.ext import commands
from twitchio import Message as Message

from tts_manager import TTSManager
from audio_manager import AudioManager

from rich import print

# Load environment variables
dotenv.load_dotenv(".env")

if os.getenv('USE_OBS', '0') == '1':
    from obswebsocket import obsws, requests
    obs = None  # Global OBS instance
    try:
        obs = obsws(
            host=os.getenv('OBS_WEBSOCKET_HOST', 'localhost'),
            port=int(os.getenv('OBS_WEBSOCKET_PORT', 4455)),
            password=os.getenv('OBS_WEBSOCKET_PASSWORD', '') if os.getenv('USE_OBS_WEBSOCKET_PASSWORD', '0') == '1' else ''
        )
        obs.connect()
        print("[bold green]Connected to OBS WebSocket successfully[/bold green]")
    except Exception as e:
        print(f"[red]Error connecting to OBS WebSocket: {e}[/red]")
        obs = None
else:
    obs = None  # OBS not used

# Initialize TTS and Audio Managers
tts_manager = TTSManager(aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                         aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                        region_name=os.getenv('AWS_REGION', 'us-east-1'))
audio_manager = AudioManager()

# Define the Twitch channel name
TWITCH_CHANNEL_NAME = os.getenv('TWITCH_CHANNEL')
if TWITCH_CHANNEL_NAME is None:
    raise ValueError("TWITCH_CHANNEL environment variable not set")

# Global instance for the bot
twitchbot = None

# Initialize the Flask app and SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'chatgodappsecret!')
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# Flag file to ensure we only initialize the bot once
BOT_FLAG_FILE = ".bot_initialized"

def refresh_twitch_token():
    """Refresh the Twitch access token using the refresh token"""
    refresh_token = os.getenv('TWITCH_REFRESH_TOKEN')
    client_id = os.getenv('TWITCH_CLIENT_ID')
    client_secret = os.getenv('TWITCH_CLIENT_SECRET')
    
    if not all([refresh_token, client_id, client_secret]):
        print("[red]Missing required Twitch credentials for token refresh![/red]")
        print(f"[yellow]TWITCH_REFRESH_TOKEN: {'✓' if refresh_token else '✗'}[/yellow]")
        print(f"[yellow]TWITCH_CLIENT_ID: {'✓' if client_id else '✗'}[/yellow]")
        print(f"[yellow]TWITCH_CLIENT_SECRET: {'✓' if client_secret else '✗'}[/yellow]")
        return False
    
    try:
        print("[cyan]Refreshing Twitch access token...[/cyan]")
        
        # Make the token refresh request
        url = "https://id.twitch.tv/oauth2/token"
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'client_id': client_id,
            'client_secret': client_secret
        }
        
        response = http_requests.post(url, data=data)
        
        if response.status_code == 200:
            token_data = response.json()
            new_access_token = token_data['access_token']
            new_refresh_token = token_data.get('refresh_token', refresh_token)  # Some responses don't include new refresh token
            
            print("[green]✓ Successfully refreshed Twitch token![/green]")
            
            # Update environment variables in memory
            os.environ['TWITCH_ACCESS_TOKEN'] = new_access_token
            os.environ['TWITCH_REFRESH_TOKEN'] = new_refresh_token
            
            # Update the .env file
            update_env_file(new_access_token, new_refresh_token)
            
            return True
        else:
            print(f"[red]Failed to refresh token. Status: {response.status_code}[/red]")
            print(f"[red]Response: {response.text}[/red]")
            return False
            
    except Exception as e:
        print(f"[red]Error refreshing Twitch token: {e}[/red]")
        return False

def update_env_file(new_access_token, new_refresh_token):
    """Update the .env file with new tokens"""
    try:
        env_file_path = '.env'
        
        # Read the current .env file
        with open(env_file_path, 'r') as f:
            lines = f.readlines()
        
        # Update the lines with new tokens
        updated_lines = []
        access_token_updated = False
        refresh_token_updated = False
        
        for line in lines:
            if line.startswith('TWITCH_ACCESS_TOKEN='):
                updated_lines.append(f'TWITCH_ACCESS_TOKEN={new_access_token}\n')
                access_token_updated = True
            elif line.startswith('TWITCH_REFRESH_TOKEN='):
                updated_lines.append(f'TWITCH_REFRESH_TOKEN={new_refresh_token}\n')
                refresh_token_updated = True
            else:
                updated_lines.append(line)
        
        # Add missing entries if they weren't found
        if not access_token_updated:
            updated_lines.append(f'TWITCH_ACCESS_TOKEN={new_access_token}\n')
        if not refresh_token_updated:
            updated_lines.append(f'TWITCH_REFRESH_TOKEN={new_refresh_token}\n')
        
        # Write the updated content back to the file
        with open(env_file_path, 'w') as f:
            f.writelines(updated_lines)
        
        print("[green]✓ Updated .env file with new tokens[/green]")
        
    except Exception as e:
        print(f"[yellow]Warning: Could not update .env file: {e}[/yellow]")
        print("[yellow]New tokens are available in memory for this session[/yellow]")

class TwitchBot(commands.Bot):
    """Twitch bot implementation"""
    
    # User tracking
    current_user_1 = None
    current_user_2 = None
    current_user_3 = None
    
    # TTS settings
    tts_enabled_1 = True
    tts_enabled_2 = True
    tts_enabled_3 = True
    
    # Voice settings - default to Joanna for all users
    voice_1 = 'Joanna'
    voice_2 = 'Joanna'
    voice_3 = 'Joanna'
    
    # Registration commands
    keypassphrase_1 = "!player1"
    keypassphrase_2 = "!player2"
    keypassphrase_3 = "!player3"
    
    # User pools
    user_pool_1 = {}  # dict of username and time last chatted
    user_pool_2 = {}  # dict of username and time last chatted
    user_pool_3 = {}  # dict of username and time last chatted
    
    # Settings
    seconds_active = 450  # seconds until a chatter is booted from the list
    max_users = 2000  # max users in user pool

    def __init__(self):
        """Initialize the bot with Twitch credentials"""
        self._shutdown = False
        super().__init__(
            token=str(os.getenv("TWITCH_ACCESS_TOKEN")),
            prefix='!', 
            initial_channels=[TWITCH_CHANNEL_NAME]
        )

    async def event_ready(self):
        """Called when the bot is ready"""
        # # Play a welcome message
        # output_path = tts_manager.text_to_speech("(drunk) Lets get ready to (breath) (deep) rumble.", voice_id='Brian')
        # audio_manager.load_audio(output_path)
        # audio_manager.play_audio(output_path)
        # audio_manager.unload_audio(output_path)
        
        print(f" * Logged in as {self.nick}")
        print(f" * Connected to channel: {', '.join([channel.name for channel in self.connected_channels])}")

    async def event_message(self, message):
        """Handle incoming messages"""
        await self.process_message(message)

    async def process_message(self, message):
        """Process incoming messages from chat"""
        # Check for registration commands
        if message.content in [self.keypassphrase_1, self.keypassphrase_2, self.keypassphrase_3]:
            self.register_user(message)
            return
            
        # Process messages from selected users
        if message.author.name == self.current_user_1:
            socketio.emit('message_send', {
                'message': f"{message.content}",
                'current_user': f"{self.current_user_1}",
                'user_number': "1"
            })
            if self.tts_enabled_1:
                # Enable OBS audio filter for this user
                control_obs_audio_filter("1", True)
                threading.Thread(
                    target=process_tts,
                    args=(message.content, "1")
                ).start()
                
        elif message.author.name == self.current_user_2:
            socketio.emit('message_send', {
                'message': f"{message.content}",
                'current_user': f"{self.current_user_2}",
                'user_number': "2"
            })
            if self.tts_enabled_2:
                # Enable OBS audio filter for this user
                control_obs_audio_filter("2", True)
                threading.Thread(
                    target=process_tts,
                    args=(message.content, "2")
                ).start()
                
        elif message.author.name == self.current_user_3:
            socketio.emit('message_send', {
                'message': f"{message.content}",
                'current_user': f"{self.current_user_3}",
                'user_number': "3"
            })
            if self.tts_enabled_3:
                # Enable OBS audio filter for this user
                control_obs_audio_filter("3", True)
                threading.Thread(
                    target=process_tts,
                    args=(message.content, "3")
                ).start()

    def register_user(self, message):
        """Register a user to the appropriate pool based on command"""
        user_pool = None
        if message.content == self.keypassphrase_1:
            user_pool = self.user_pool_1
        elif message.content == self.keypassphrase_2:
            user_pool = self.user_pool_2
        elif message.content == self.keypassphrase_3:
            user_pool = self.user_pool_3
        else:
            return
            
        # Remove user if already in pool (to update timestamp)
        if message.author.name.lower() in user_pool:
            user_pool.pop(message.author.name.lower())
            
        # Add user to pool with current timestamp
        user_pool[message.author.name.lower()] = message.timestamp
        
        # Check for inactive users or if pool is too large
        self.clean_user_pool(user_pool)

    def clean_user_pool(self, user_pool):
        """Remove inactive users from the pool"""
        if not user_pool:
            return
            
        activity_threshold = datetime.now(pytz.utc) - timedelta(seconds=self.seconds_active)
        
        # Get the oldest user (first in the dict)
        if user_pool:
            oldest_user = list(user_pool.keys())[0]
            # Check if user is inactive or pool is too large
            if (user_pool[oldest_user].replace(tzinfo=pytz.utc) < activity_threshold or 
                len(user_pool) > self.max_users):
                user_pool.pop(oldest_user)
                if len(user_pool) == self.max_users:
                    print(f"[yellow]{oldest_user} was removed due to hitting max users[/yellow]")
                else:
                    print(f"[yellow]{oldest_user} was removed due to not talking for {self.seconds_active} seconds[/yellow]")

    def random_user(self, user_number):
        """Pick a random user from the appropriate pool"""
        try:
            user_pool = None
            if user_number == "1":
                user_pool = self.user_pool_1
                if user_pool:
                    self.current_user_1 = random.choice(list(user_pool.keys()))
                    emit_user_update(user_number, self.current_user_1)
            elif user_number == "2":
                user_pool = self.user_pool_2
                if user_pool:
                    self.current_user_2 = random.choice(list(user_pool.keys()))
                    emit_user_update(user_number, self.current_user_2)
            elif user_number == "3":
                user_pool = self.user_pool_3
                if user_pool:
                    self.current_user_3 = random.choice(list(user_pool.keys()))
                    emit_user_update(user_number, self.current_user_3)
        except Exception as e:
            print(f"[red]Error selecting random user: {e}[/red]")

    def should_shutdown(self):
        """Check if the bot should shut down"""
        return self._shutdown
        
    async def close(self):
        """Override close method to handle shutdown"""
        self._shutdown = True
        await super().close()


# --- Web App Routes and Event Handlers ---

@app.route("/")
def home():
    """Render the main page"""
    return render_template('index.html')

@app.route("/obs")
def obs_overlay():
    """Render a transparent overlay for OBS with a single user"""
    user_number = request.args.get('user', '1')
    
    # Try to convert to int to check validity
    try:
        user_num = int(user_number)
        # For now, validate against 1, 2, 3 (can be expanded if dynamic user system is implemented)
        if user_num not in [1, 2, 3]:
            user_number = '1'  # Default to user 1 if invalid
    except ValueError:
        user_number = '1'  # Default to user 1 if not a number
        
    return render_template('obs.html', user_number=user_number)

@socketio.event
def connect(auth=None):
    """Handle client connection event"""
    for i in range(1, 4):
        socketio.emit('message_send', {
            'message': "This is a temporary message",
            'current_user': "Temp User",
            'user_number': str(i)
        })

@socketio.on("tts")
def toggle_tts(value):
    """Toggle TTS for a specific user slot"""
    global twitchbot
    
    if twitchbot is None:
        print("[red]TwitchBot not initialized, can't toggle TTS[/red]")
        return
    
    print(f"[cyan]TTS: Received the value {str(value['checked'])} for user {value['user_number']}[/cyan]")
    
    try:
        if value['user_number'] == "1":
            twitchbot.tts_enabled_1 = value['checked']
        elif value['user_number'] == "2":
            twitchbot.tts_enabled_2 = value['checked']
        elif value['user_number'] == "3":
            twitchbot.tts_enabled_3 = value['checked']
    except Exception as e:
        print(f"[red]Error toggling TTS: {e}[/red]")

@socketio.on("pickrandom")
def pick_random(value):
    """Pick a random user for the specified slot"""
    global twitchbot
    
    if twitchbot is None:
        print("[red]TwitchBot not initialized, can't pick random user[/red]")
        return
    
    try:    
        twitchbot.random_user(value['user_number'])
        print(f"[magenta]Getting new random user for user {value['user_number']}[/magenta]")
    except Exception as e:
        print(f"[red]Error picking random user: {e}[/red]")

@socketio.on("choose")
def choose_user(value):
    """Choose a specific user for the specified slot"""
    global twitchbot
    
    if twitchbot is None:
        print("[red]TwitchBot not initialized, can't choose user[/red]")
        return
    
    user_number = value['user_number']
    chosen_user = value['chosen_user'].lower()
    
    try:
        if user_number == "1":
            twitchbot.current_user_1 = chosen_user
            emit_user_update(user_number, chosen_user)
        elif user_number == "2":
            twitchbot.current_user_2 = chosen_user
            emit_user_update(user_number, chosen_user)
        elif user_number == "3":
            twitchbot.current_user_3 = chosen_user
            emit_user_update(user_number, chosen_user)
    except Exception as e:
        print(f"[red]Error choosing user: {e}[/red]")

@socketio.on("voice_change")
def change_voice(value):
    """Change the voice for a specific user slot"""
    global twitchbot
    
    if twitchbot is None:
        print("[red]TwitchBot not initialized, can't change voice[/red]")
        return
    
    user_number = value['user_number']
    voice_id = value['voice_id']
    
    print(f"[green]Voice: Changing voice for user {user_number} to {voice_id}[/green]")
    
    try:
        if user_number == "1":
            twitchbot.voice_1 = voice_id
        elif user_number == "2":
            twitchbot.voice_2 = voice_id
        elif user_number == "3":
            twitchbot.voice_3 = voice_id
    except Exception as e:
        print(f"[red]Error changing voice: {e}[/red]")


# --- Helper Functions ---

def control_obs_audio_filter(user_number, enable):
    """Enable/disable OBS audio move filter for a specific user"""
    global obs, requests

    if not obs or os.getenv('USE_OBS', '0') != '1':
        print(f"[yellow]OBS not available or disabled. OBS: {obs}, USE_OBS: {os.getenv('USE_OBS', '0')}[/yellow]")
        return
    
    try:
        # Get the main audio source (typically the same for all users)
        source_name = os.getenv('OBS_SOURCE', 'Line In')
        
        # Get filter names for each user
        if user_number == "1":
            filter_name = os.getenv('OBS_AUDIO_MOVE_FILTER_1', 'Audio Move Filter 1')
        elif user_number == "2":
            filter_name = os.getenv('OBS_AUDIO_MOVE_FILTER_2', 'Audio Move Filter 2')
        elif user_number == "3":
            filter_name = os.getenv('OBS_AUDIO_MOVE_FILTER_3', 'Audio Move Filter 3')
        else:
            print(f"[red]Invalid user number: {user_number}[/red]")
            return
        
        print(f"[cyan]OBS Control: User {user_number}, Source: {source_name}, Filter: {filter_name}, Enable: {enable}[/cyan]")
        
        # Enable/disable the filter for the current user
        if enable:
            obs.call(requests.SetSourceFilterEnabled(
                sourceName=source_name,
                filterName=filter_name,
                filterEnabled=True
            ))
            print(f"[green]Enabled OBS audio filter '{filter_name}' for user {user_number}[/green]")
        else:
            obs.call(requests.SetSourceFilterEnabled(
                sourceName=source_name,
                filterName=filter_name,
                filterEnabled=False
            ))
            print(f"[yellow]Disabled OBS audio filter '{filter_name}' for user {user_number}[/yellow]")
            
    except Exception as e:
        print(f"[red]Error controlling OBS audio filter for user {user_number}: {e}[/red]")

def emit_user_update(user_number, username):
    """Emit a message that a user has been selected"""
    # This event is received by both the main page and the OBS overlay
    socketio.emit('message_send', {
        'message': f"{username} was picked!",
        'current_user': f"{username}",
        'user_number': user_number
    })

def process_tts(message, user_number):
    """Process text-to-speech for a message"""
    global twitchbot
    
    # Get the appropriate voice for this user
    voice_id = 'Joanna'  # Default fallback
    if twitchbot:
        if user_number == "1":
            voice_id = twitchbot.voice_1
        elif user_number == "2":
            voice_id = twitchbot.voice_2
        elif user_number == "3":
            voice_id = twitchbot.voice_3
    
    output_path = tts_manager.text_to_speech(message, voice_id=voice_id)
    audio_manager.load_audio(output_path)
    audio_manager.play_audio(output_path)
    
    # Emit the audio play event to the client for UI feedback
    socketio.emit('play_audio', {
        'user_number': user_number,
        'message': message
    })
    
    # get length of audio file to determine how long to play it
    audio_length = audio_manager.get_audio_length(output_path)

    # Clean up after playing
    audio_manager.unload_audio(output_path)

    time.sleep(audio_length + .3)  # Wait for the audio to finish playing
    
    # Disable the OBS audio filter after TTS finishes
    control_obs_audio_filter(user_number, False)

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    print("\n[bold red]Shutting down...[/bold red]")
    
    # Clean up the bot flag file
    if os.path.exists(BOT_FLAG_FILE):
        try:
            os.remove(BOT_FLAG_FILE)
        except:
            pass
    
    if twitchbot:
        twitchbot._shutdown = True
        try:
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(loop.stop)
        except:
            pass
    
    sys.exit(0)

def start_twitch_bot():
    """Start the Twitch bot on a separate thread"""
    global twitchbot

    if os.path.exists(BOT_FLAG_FILE):
        print("[yellow]Bot initialization flag exists, another process may have already initialized the bot[/yellow]")
        exit(1)
        
    if twitchbot is None:  # Only start if not already running
        try:
            # Refresh Twitch access token before starting the bot
            print("[bold blue]Refreshing Twitch credentials...[/bold blue]")
            if not refresh_twitch_token():
                print("[bold red]Failed to refresh Twitch token. Cannot start bot.[/bold red]")
                return None
            
            # Create flag file to indicate we're initializing the bot
            with open(BOT_FLAG_FILE, 'w') as f:
                f.write('initialized')
                
            print("[bold cyan]Initializing Twitch bot...[/bold cyan]")
            # Initialize the bot with a dedicated event loop in a separate thread
            bot_thread = threading.Thread(target=initialize_and_run_bot, daemon=True)
            bot_thread.start()
            
            # Give it a moment to initialize
            time.sleep(2)
            print("[bold green]Twitch bot started and running on a separate thread.[/bold green]")
        except Exception as e:
            print(f"[bold red]Error starting TwitchBot: {e}[/bold red]")
            twitchbot = None
            # Remove flag file if initialization failed
            if os.path.exists(BOT_FLAG_FILE):
                os.remove(BOT_FLAG_FILE)
            
    return twitchbot

def initialize_and_run_bot():
    """Initialize the bot with a new event loop and run it"""
    global twitchbot

    try:
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Initialize the bot
        twitchbot = TwitchBot()
        print("[bold green]TwitchBot initialized successfully[/bold green]")
        
        # Run the bot
        twitchbot.run()
    except Exception as e:
        print(f"[bold red]Error in initialize_and_run_bot: {e}[/bold red]")
        twitchbot = None


if __name__ == '__main__':
    # Ensure we're in the correct directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    
    # Remove any leftover flag file from previous runs
    if os.path.exists(BOT_FLAG_FILE):
        os.remove(BOT_FLAG_FILE)
    
    # Start the Twitch bot before running the web app
    print("[bold blue]Starting Twitch bot...[/bold blue]")
    start_twitch_bot()
    
    # Start the Flask app with Socket.IO
    print("[bold blue]Starting web server. Press Ctrl+C to stop.[/bold blue]")
    socketio.run(app, port=8080, debug=True, use_reloader=False, host='0.0.0.0', allow_unsafe_werkzeug=True)