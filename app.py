import asyncio
import base64
import io
import platform
import random
import re
import subprocess
import wave
import edge_tts
import psutil
import requests
import sounddevice as sd
import speech_recognition as sr
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "hermes3"
TTS_VOICE = "en-US-AvaNeural"

SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "You are Aura, Błażej's concise technical companion. "
        "Stay strictly on topic and answer directly in 1 to 2 short sentences maximum. "
        "No rambling, no unprompted tangents, and no filler intros. "
        "Sound natural and human, using contractions, without sounding like a customer service bot. "
        "STRICT RULE: Never output emojis, emoticons, asterisks, markdown, or special symbols."
    )
}

FILLER_PHRASES = [
    "Let me check that real quick.",
    "One sec, checking now.",
    "Pulling that up."
]

chat_history = [SYSTEM_PROMPT]

def clean_for_speech(text):
    # Remove emojis, pictographs, markdown symbols (*, #, _, ~), and extra spaces
    text = re.sub(r'[^\x00-\x7FąćęłńóśźżĄĆĘŁŃÓŚŹŻ.,!?\'"()\-:;/%0-9a-zA-Z\s]', '', text)
    text = re.sub(r'[*#_~`]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def get_system_telemetry():
    cpu = psutil.cpu_percent(interval=0.2)
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage('C:\\' if platform.system().lower() == "windows" else '/').percent
    return f"Host OS: {platform.system()} | CPU: {cpu}% | RAM: {ram}% | Disk: {disk}%"

def ping_node(ip_address):
    param = "-n" if platform.system().lower() == "windows" else "-c"
    try:
        output = subprocess.run(
            ["ping", param, "2", ip_address],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5
        )
        status = "ONLINE" if output.returncode == 0 else "UNREACHABLE"
        return f"Node {ip_address}: {status}"
    except Exception as e:
        return f"Node {ip_address}: PING ERROR ({str(e)})"

def needs_live_check(user_msg):
    msg_lower = user_msg.lower()
    keywords = ["status", "system", "cpu", "ram", "health", "telemetry", "pi", "router", "10.0.1.1", "proxmox", "server", "check", "ping"]
    return any(k in msg_lower for k in keywords)

def check_homelab_context(user_msg):
    msg_lower = user_msg.lower()
    injected_data = []
    if any(k in msg_lower for k in ["status", "system", "cpu", "ram", "health", "telemetry"]):
        injected_data.append(get_system_telemetry())
    if "pi" in msg_lower or "router" in msg_lower or "10.0.1.1" in msg_lower:
        injected_data.append(ping_node("10.0.1.1"))
    if "proxmox" in msg_lower or "server" in msg_lower:
        injected_data.append(ping_node("192.168.1.100"))
    return "\n".join(injected_data)

async def generate_tts_base64(text):
    clean_text = clean_for_speech(text)
    if not clean_text:
        return None
    communicate = edge_tts.Communicate(clean_text, TTS_VOICE, pitch="+2Hz", rate="+4%")
    audio_bytes = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_bytes.write(chunk["data"])
    return base64.b64encode(audio_bytes.getvalue()).decode("utf-8")

def record_voice_wav(seconds=4.5, sample_rate=16000):
    frames = sd.rec(int(seconds * sample_rate), samplerate=sample_rate, channels=1, dtype="int16")
    sd.wait()
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames.tobytes())
    wav_buffer.seek(0)
    return wav_buffer

@app.route("/")
def index():
    resp = app.make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

@app.route("/listen", methods=["POST"])
def listen():
    recognizer = sr.Recognizer()
    try:
        wav_data = record_voice_wav(seconds=4.5)
        with sr.AudioFile(wav_data) as source:
            audio = recognizer.record(source)
        transcript = recognizer.recognize_google(audio)
        return jsonify({"success": True, "text": transcript})
    except sr.UnknownValueError:
        return jsonify({"success": False, "error": "Didn't catch that..."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/precheck", methods=["POST"])
def precheck():
    user_message = request.json.get("message", "").strip()
    if needs_live_check(user_message):
        phrase = random.choice(FILLER_PHRASES)
        audio_b64 = asyncio.run(generate_tts_base64(phrase))
        return jsonify({"has_filler": True, "text": phrase, "audio": audio_b64})
    return jsonify({"has_filler": False})

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    telemetry = check_homelab_context(user_message)
    prompt_to_send = user_message
    if telemetry:
        prompt_to_send = (
            f"{user_message}\n\n"
            f"[LIVE DATA]:\n{telemetry}\n"
            f"Give only the direct answer in 1-2 short sentences. No emojis."
        )

    chat_history.append({"role": "user", "content": prompt_to_send})
    recent_messages = [SYSTEM_PROMPT] + chat_history[-10:]

    payload = {
        "model": MODEL_NAME,
        "messages": recent_messages,
        "options": {
            "num_predict": 65,
            "temperature": 0.65,
            "top_p": 0.85,
            "repeat_penalty": 1.15
        },
        "stream": False
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=60)
        response.raise_for_status()
        raw_reply = response.json().get("message", {}).get("content", "Glitch on my end, say that again.")
        ai_reply = clean_for_speech(raw_reply)
        chat_history.append({"role": "assistant", "content": ai_reply})

        audio_b64 = asyncio.run(generate_tts_base64(ai_reply))
        return jsonify({"reply": ai_reply, "audio": audio_b64})
    except Exception as e:
        return jsonify({"reply": f"Ollama connection error: {str(e)}", "audio": None})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
