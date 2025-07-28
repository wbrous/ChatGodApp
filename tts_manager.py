import boto3
import os
import tempfile

class TTSManager:
    def __init__(self, aws_access_key_id=None, aws_secret_access_key=None, region_name='us-east-1'):
        self.polly = boto3.client(
            'polly',
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name
        )

    def format_text(self, text):
        emotions = {
            'high': ['<prosody pitch="+30%">', '</prosody>'],
            'higher': ['<amazon:effect vocal-tract-length="-80%">', '</amazon:effect>'],
            'deep': ['<prosody pitch="-30%">', '</prosody>'],
            'deeper': ['<amazon:effect vocal-tract-length="+80%">', '</amazon:effect>'],
            'drunk': ['<prosody rate="x-slow">', '</prosody>'],
            'asthma': ['<amazon:auto-breaths volume="x-loud" frequency="x-high", duration="x-short">', '</amazon:auto-breaths>'],
            'soft': ['<prosody volume="x-soft">', '</prosody>'],
            'loud': ['<prosody volume="x-loud">', '</prosody>'],
            'whisper': ['<amazon:effect name="whispered">', '</amazon:effect>'],
            'breath': '<amazon:breath duration="x-long" volume="x-loud"/>',
        }

        import re
        
        # Separate emotion markers and normal text
        parts = []
        last_end = 0
        
        # Find all emotion markers in the text
        for match in re.finditer(r'\((\w+)\)', text):
            # Add text before this marker
            if match.start() > last_end:
                parts.append({
                    'type': 'text',
                    'content': text[last_end:match.start()]
                })
            
            # Add the marker
            emotion = match.group(1).lower()
            if emotion in emotions:
                parts.append({
                    'type': 'emotion',
                    'emotion': emotion
                })
            
            last_end = match.end()
        
        # Add any remaining text after the last marker
        if last_end < len(text):
            parts.append({
                'type': 'text',
                'content': text[last_end:]
            })
        
        # Process the parts to build the final SSML
        result = []
        current_effect = None
        
        for i, part in enumerate(parts):
            if part['type'] == 'text':
                result.append(part['content'])
            elif part['type'] == 'emotion':
                emotion = part['emotion']
                
                # Handle the emotion
                if emotion in emotions:
                    if isinstance(emotions[emotion], list):
                        # If we have an active effect, close it
                        if current_effect:
                            result.append(emotions[current_effect][1])
                        
                        # Open the new effect
                        result.append(emotions[emotion][0])
                        current_effect = emotion
                    else:
                        # Single tag like breath
                        result.append(emotions[emotion])
        
        # Close the last effect if one is open
        if current_effect:
            result.append(emotions[current_effect][1])
        
        # Join the result and wrap in SSML tags
        return f'<speak>{"".join(result)}</speak>'

    def text_to_speech(self, text, output_path=None, format_text=True, voice_id='Joanna', output_format='mp3'):
        if format_text:
            text = self.format_text(text)
        response = self.polly.synthesize_speech(
            Text=text,
            VoiceId=voice_id,
            OutputFormat=output_format,
            TextType='ssml' if text.strip().startswith('<speak>') else 'text'
        )
        audio_stream = response.get('AudioStream')
        if audio_stream:
            if output_path:
                with open(output_path, 'wb') as f:
                    f.write(audio_stream.read())
                return output_path
            else:
                fd, output_path = tempfile.mkstemp(suffix=f'.{output_format}')
                os.close(fd)
                with open(output_path, 'wb') as f:
                    f.write(audio_stream.read())
            return output_path
        return None