from flask import Blueprint, request, jsonify
import subprocess
import requests

ai_bp = Blueprint('ai_bp', __name__)


@ai_bp.route('/api/ai', methods=['POST'])
def ai_chat():
    data = request.get_json()
    question = data.get("question", "").strip()

    if not question:
        return jsonify({"error": "Pas de question fournie"}), 400

    # 2️⃣ Essayer Ollama
    try:
        ollama_proc = subprocess.run(
            ["ollama", "run", "llama3", question],
            capture_output=True,
            text=True,
        )
        ollama_answer = ollama_proc.stdout.strip()
        return jsonify({"response": f"Ollama: {ollama_answer}"})
    except subprocess.SubprocessError as e:
        return jsonify({"error": f"Erreur Ollama: {str(e)}"}), 500
