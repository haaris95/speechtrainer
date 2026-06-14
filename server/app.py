import base64
import json
import mimetypes
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = Path(__file__).resolve().parents[1]
VENDOR_DIR = SERVER_DIR / ".python-packages"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

import azure.cognitiveservices.speech as speechsdk


def load_dotenv(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#") or "=" not in cleaned:
            continue
        key, value = cleaned.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv(SERVER_DIR / ".env")

PORT = int(os.environ.get("PORT", "8789"))
SPEECH_KEY = os.environ.get("AZURE_SPEECH_KEY")
SPEECH_REGION = os.environ.get("AZURE_SPEECH_REGION", "eastus")
PROJECT_ENDPOINT = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
MODEL = os.environ.get("FOUNDRY_MODEL", "gpt-4.1-mini")
AGENT_NAME = os.environ.get("FOUNDRY_AGENT_NAME", "speechtrainer")
AGENT_VERSION = os.environ.get("FOUNDRY_AGENT_VERSION", "1")
AUTH_TOKEN = os.environ.get("AZURE_AI_AUTH_TOKEN")


class SpeechTrainerHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/evaluate-speaking":
            self.handle_evaluate_speaking()
            return
        if self.path == "/api/generate-questions":
            self.handle_generate_questions()
            return
        if self.path == "/api/generate-question":
            self.handle_generate_question()
            return
        if self.path == "/api/evaluate-answer":
            self.handle_evaluate_answer()
            return
        if self.path == "/api/final-report":
            self.handle_final_report()
            return
        self.send_json(404, {"error": "not_found"})

    def do_GET(self):
        if self.path == "/api/health":
            self.send_json(
                200,
                {
                    "azureSpeechKey": "SET" if SPEECH_KEY else "MISSING",
                    "azureSpeechRegion": SPEECH_REGION or "MISSING",
                    "foundryProjectEndpoint": "SET" if PROJECT_ENDPOINT else "MISSING",
                    "foundryModel": MODEL or "MISSING",
                    "foundryAuthToken": "SET" if AUTH_TOKEN else "MISSING",
                },
            )
            return

        safe_path = self.path.split("?", 1)[0]
        if safe_path == "/":
            safe_path = "/index.html"

        file_path = (PUBLIC_DIR / safe_path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(PUBLIC_DIR)) or not file_path.exists():
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def handle_evaluate_speaking(self):
        try:
            payload = self.read_json()
            result = evaluate_speaking(payload.get("answers", []))
            self.send_json(200, result)
        except Exception as exc:
            self.send_json(
                500,
                {
                    "error": "speaking_evaluation_failed",
                    "message": str(exc),
                },
            )

    def handle_generate_questions(self):
        try:
            payload = self.read_json()
            result = generate_questions(
                target_band=payload.get("targetBand", "6.5"),
                topic_preference=payload.get("topicPreference", "general IELTS speaking topics"),
            )
            self.send_json(200, result)
        except Exception as exc:
            self.send_json(
                500,
                {
                    "error": "question_generation_failed",
                    "message": str(exc),
                },
            )

    def handle_generate_question(self):
        try:
            payload = self.read_json()
            result = generate_question(
                question_index=int(payload.get("questionIndex", 0)),
                total_questions=int(payload.get("totalQuestions", 5)),
                target_band=payload.get("targetBand", "6.5"),
                topic_preference=payload.get("topicPreference", "general IELTS speaking topics"),
                previous_questions=payload.get("previousQuestions", []),
                previous_answer_summaries=payload.get("previousAnswerSummaries", []),
            )
            self.send_json(200, result)
        except Exception as exc:
            self.send_json(
                500,
                {
                    "error": "single_question_generation_failed",
                    "message": str(exc),
                },
            )

    def handle_evaluate_answer(self):
        try:
            payload = self.read_json()
            result = evaluate_answer(payload.get("answer", {}))
            self.send_json(200, result)
        except Exception as exc:
            self.send_json(
                500,
                {
                    "error": "answer_evaluation_failed",
                    "message": str(exc),
                },
            )

    def handle_final_report(self):
        try:
            payload = self.read_json()
            result = final_report(payload.get("answerReports", []))
            self.send_json(200, result)
        except Exception as exc:
            self.send_json(
                500,
                {
                    "error": "final_report_failed",
                    "message": str(exc),
                },
            )

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8")
        return json.loads(raw_body or "{}")

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def evaluate_speaking(answers):
    if not SPEECH_KEY:
        raise RuntimeError("Azure Speech is not configured. Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION.")
    if not PROJECT_ENDPOINT or not AUTH_TOKEN:
        raise RuntimeError("Foundry is not configured. Set FOUNDRY_PROJECT_ENDPOINT and AZURE_AI_AUTH_TOKEN.")

    speech_results = [assess_pronunciation(answer) for answer in answers]
    foundry_report = call_foundry(speech_results)
    return {
        **normalize_foundry_report(foundry_report),
        "speechResults": speech_results,
    }


def evaluate_answer(answer):
    if not SPEECH_KEY:
        raise RuntimeError("Azure Speech is not configured. Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION.")
    if not PROJECT_ENDPOINT or not AUTH_TOKEN:
        raise RuntimeError("Foundry is not configured. Set FOUNDRY_PROJECT_ENDPOINT and AZURE_AI_AUTH_TOKEN.")

    speech_result = assess_pronunciation(answer)
    prompt = f"""
You are an IELTS speaking examiner.
Evaluate this single IELTS speaking answer using Azure AI Speech metrics and transcript.
Return only JSON:
{{
  "question": "",
  "part": "",
  "estimatedBand": 0,
  "fluencyBand": 0,
  "pronunciationBand": 0,
  "vocabularyBand": 0,
  "grammarBand": 0,
  "strength": "",
  "improvement": "",
  "privateFeedback": "",
  "practiceDrill": ""
}}

Rules:
- This is a practice estimate, not an official IELTS score.
- Be specific and professional.
- Do not reveal this feedback to the user yet; it will be stored until the final report.
- Your entire response must be valid JSON parseable by Python json.loads.
- Use double quotes around every property name and string value.
- Do not include markdown fences, comments, or explanatory text.

Answer data:
{json.dumps(speech_result, indent=2)}
"""
    report = call_foundry_prompt(prompt)
    return {
        "question": str(report.get("question") or speech_result.get("question") or ""),
        "part": str(report.get("part") or speech_result.get("part") or ""),
        "estimatedBand": float(report.get("estimatedBand") or 0),
        "fluencyBand": float(report.get("fluencyBand") or 0),
        "pronunciationBand": float(report.get("pronunciationBand") or report.get("fluencyBand") or 0),
        "vocabularyBand": float(report.get("vocabularyBand") or 0),
        "grammarBand": float(report.get("grammarBand") or 0),
        "strength": str(report.get("strength") or ""),
        "improvement": str(report.get("improvement") or ""),
        "privateFeedback": str(report.get("privateFeedback") or ""),
        "practiceDrill": str(report.get("practiceDrill") or ""),
        "speechResult": speech_result,
    }


def final_report(answer_reports):
    if not PROJECT_ENDPOINT or not AUTH_TOKEN:
        raise RuntimeError("Foundry is not configured. Set FOUNDRY_PROJECT_ENDPOINT and AZURE_AI_AUTH_TOKEN.")
    if not isinstance(answer_reports, list) or not answer_reports:
        raise ValueError("No stored answer reports were provided.")

    prompt = f"""
You are an IELTS speaking examiner preparing a final business-style performance report.
Use the stored per-answer evaluations below. Return only JSON:
{{
  "overallBand": 0,
  "fluencyBand": 0,
  "pronunciationBand": 0,
  "vocabularyBand": 0,
  "grammarBand": 0,
  "feedback": ["professional summary item"],
  "answerBreakdown": [{{"question": "", "strength": "", "improvement": ""}}]
}}

Rules:
- This is a practice estimate, not an official IELTS score.
- Keep the tone polished, concise, and useful.
- Include concrete next steps.
- Your entire response must be valid JSON parseable by Python json.loads.
- Use double quotes around every property name and string value.
- Do not include markdown fences, comments, or explanatory text.

Stored answer evaluations:
{json.dumps(answer_reports, indent=2)}
"""
    return normalize_foundry_report(call_foundry_prompt(prompt))


def generate_question(question_index, total_questions, target_band, topic_preference, previous_questions, previous_answer_summaries):
    if not PROJECT_ENDPOINT or not AUTH_TOKEN:
        raise RuntimeError("Foundry question generation is not configured. Set FOUNDRY_PROJECT_ENDPOINT and AZURE_AI_AUTH_TOKEN.")

    part_plan = question_plan(question_index)
    prompt = f"""
You are an IELTS speaking examiner conducting a live mock interview.
Generate exactly one next question for turn {question_index + 1} of {total_questions}.
Target band: {target_band}
Topic preference: {topic_preference}
Required IELTS section: {part_plan["part"]}
Required section title: {part_plan["title"]}

Return only JSON:
{{
  "part": "{part_plan["part"]}",
  "title": "{part_plan["title"]}",
  "text": "...",
  "hint": "..."
}}

Previous questions to avoid repeating:
{json.dumps(previous_questions, indent=2)}

Private summaries of previous answers, useful for natural follow-up:
{json.dumps(previous_answer_summaries, indent=2)}

Rules:
- Use realistic IELTS-style wording.
- If this is Part 2, include "You should say..." prompts in one sentence.
- If this is Part 3, ask a broader abstract discussion question related to the session.
- Hint must be short coaching guidance, not an answer.
- Your entire response must be valid JSON parseable by Python json.loads.
- Use double quotes around every property name and string value.
- Do not include markdown fences, comments, or explanatory text.
"""
    question = call_foundry_prompt(prompt)
    return {"source": "foundry", "question": validate_question(question, part_plan)}


def question_plan(index):
    plans = [
        {"part": "Part 1", "title": "Introduction and Interview"},
        {"part": "Part 1", "title": "Introduction and Interview"},
        {"part": "Part 2", "title": "Long Turn"},
        {"part": "Part 3", "title": "Discussion"},
        {"part": "Part 3", "title": "Discussion"},
    ]
    return plans[min(max(index, 0), len(plans) - 1)]


def validate_question(candidate_question, part_plan):
    if not isinstance(candidate_question, dict):
        raise ValueError("Foundry did not return a question object.")
    part = str(candidate_question.get("part") or part_plan["part"]).strip()
    title = str(candidate_question.get("title") or part_plan["title"]).strip()
    text = str(candidate_question.get("text") or "").strip()
    hint = str(candidate_question.get("hint") or "").strip()
    if not text or not hint:
        raise ValueError("Foundry question is missing text or hint.")
    return {
        "part": part,
        "title": title,
        "text": text,
        "hint": hint,
    }


def generate_questions(target_band, topic_preference):
    if not PROJECT_ENDPOINT or not AUTH_TOKEN:
        raise RuntimeError("Foundry question generation is not configured. Set FOUNDRY_PROJECT_ENDPOINT and AZURE_AI_AUTH_TOKEN.")

    prompt = f"""
You are an IELTS speaking examiner.
Generate one fresh IELTS Speaking mock test for a learner targeting band {target_band}.
Topic preference: {topic_preference}

Return only JSON:
{{
  "questions": [
    {{"part": "Part 1", "title": "Introduction and Interview", "text": "...", "hint": "..."}},
    {{"part": "Part 1", "title": "Introduction and Interview", "text": "...", "hint": "..."}},
    {{"part": "Part 2", "title": "Long Turn", "text": "...", "hint": "..."}},
    {{"part": "Part 3", "title": "Discussion", "text": "...", "hint": "..."}},
    {{"part": "Part 3", "title": "Discussion", "text": "...", "hint": "..."}}
  ]
}}

Rules:
- Use realistic IELTS-style wording.
- Part 2 must include "You should say..." bullet-style prompts in one sentence.
- Hints should be short coaching guidance, not answers.
- Do not mention that you are an AI model.
- Your entire response must be valid JSON parseable by Python json.loads.
- Use double quotes around every property name and string value.
- Do not include markdown fences, comments, or explanatory text.
"""
    print(f"Generated question prompt:\n{prompt}\n")
    report = call_foundry_prompt(prompt)
    questions = validate_questions(report.get("questions"))
    return {"source": "foundry", "questions": questions}


def validate_questions(candidate_questions):
    if not isinstance(candidate_questions, list) or len(candidate_questions) < 5:
        raise ValueError("Foundry did not return at least five IELTS questions.")
    cleaned = []
    for index, question in enumerate(candidate_questions[:5]):
        if not isinstance(question, dict):
            raise ValueError(f"Question {index + 1} is not an object.")
        part = str(question.get("part") or "").strip()
        title = str(question.get("title") or "").strip()
        text = str(question.get("text") or "").strip()
        hint = str(question.get("hint") or "").strip()
        if not part or not title or not text or not hint:
            raise ValueError(f"Question {index + 1} is missing part, title, text, or hint.")
        cleaned.append(
            {
                "part": part,
                "title": title,
                "text": text,
                "hint": hint,
            }
        )
    return cleaned


def assess_pronunciation(answer):
    audio_bytes = data_url_to_bytes(answer.get("audioDataUrl", ""))
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio_file:
        audio_file.write(audio_bytes)
        audio_path = audio_file.name

    try:
        speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
        speech_config.speech_recognition_language = "en-US"
        speech_config.output_format = speechsdk.OutputFormat.Detailed
        audio_config = speechsdk.audio.AudioConfig(filename=audio_path)
        recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

        pronunciation_config = speechsdk.PronunciationAssessmentConfig(
            reference_text="",
            grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
            granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
            enable_miscue=True,
        )
        if hasattr(pronunciation_config, "enable_prosody_assessment"):
            pronunciation_config.enable_prosody_assessment()
        pronunciation_config.apply_to(recognizer)

        result = recognizer.recognize_once_async().get()
        pronunciation_result = speechsdk.PronunciationAssessmentResult(result)
        raw_json = result.properties.get(speechsdk.PropertyId.SpeechServiceResponse_JsonResult)
        detailed = json.loads(raw_json) if raw_json else {}
        best_result = (detailed.get("NBest") or [{}])[0]
        words = best_result.get("Words") or []

        return {
            "question": answer.get("question", ""),
            "part": answer.get("part", ""),
            "browserTranscript": answer.get("transcript", ""),
            "recognizedTranscript": result.text or best_result.get("Display", ""),
            "durationSeconds": answer.get("durationSeconds", 0),
            "azureSpeech": {
                "recognitionReason": str(result.reason),
                "accuracyScore": pronunciation_result.accuracy_score,
                "fluencyScore": pronunciation_result.fluency_score,
                "completenessScore": pronunciation_result.completeness_score,
                "pronunciationScore": pronunciation_result.pronunciation_score,
                "prosodyScore": getattr(pronunciation_result, "prosody_score", None),
                "words": [
                    {
                        "word": word.get("Word"),
                        "accuracyScore": (word.get("PronunciationAssessment") or {}).get("AccuracyScore"),
                        "errorType": (word.get("PronunciationAssessment") or {}).get("ErrorType"),
                    }
                    for word in words
                ],
            },
        }
    finally:
        safe_unlink(audio_path)


def call_foundry(speech_results):
    prompt = f"""
You are an IELTS speaking examiner and coach.
Use Azure AI Speech pronunciation assessment metrics and transcripts to estimate IELTS-style bands.
Return only JSON:
{{
  "overallBand": 0,
  "fluencyBand": 0,
  "pronunciationBand": 0,
  "vocabularyBand": 0,
  "grammarBand": 0,
  "feedback": ["specific feedback item"],
  "answerBreakdown": [{{"question": "", "strength": "", "improvement": ""}}]
}}

Important:
- This is a practice estimate, not an official IELTS score.
- Fluency should consider Azure fluency/prosody scores, duration, answer completeness, pacing, pauses, and coherence.
- Pronunciation should consider Azure accuracy, pronunciation, prosody, and word-level issues.
- Explain how to improve each answer.
- You are running as the {AGENT_NAME} Foundry agent, version {AGENT_VERSION}.

Answers:
{json.dumps(speech_results, indent=2)}
"""
    return call_foundry_prompt(prompt)


def call_foundry_prompt(prompt):
    endpoint = PROJECT_ENDPOINT.rstrip("/") + "/openai/v1/responses"
    request_body = json.dumps({"model": MODEL, "input": prompt}).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=request_body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AUTH_TOKEN}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Foundry request failed: {exc.code} {detail}") from exc

    return parse_json_output(extract_foundry_text(payload))


def extract_foundry_text(payload):
    if payload.get("output_text"):
        return payload["output_text"]

    text_parts = []
    for item in payload.get("output", []):
      for content in item.get("content", []):
          if "text" in content:
              text_parts.append(content["text"])
    return "\n".join(text_parts)


def parse_json_output(text):
    cleaned = (text or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def normalize_foundry_report(report):
    return {
        "overallBand": float(report.get("overallBand") or 0),
        "fluencyBand": float(report.get("fluencyBand") or 0),
        "pronunciationBand": float(report.get("pronunciationBand") or report.get("fluencyBand") or 0),
        "vocabularyBand": float(report.get("vocabularyBand") or 0),
        "grammarBand": float(report.get("grammarBand") or 0),
        "feedback": report.get("feedback") if isinstance(report.get("feedback"), list) else [],
        "answerBreakdown": report.get("answerBreakdown") if isinstance(report.get("answerBreakdown"), list) else [],
    }


def data_url_to_bytes(data_url):
    if "," not in data_url:
        return b""
    return base64.b64decode(data_url.split(",", 1)[1])


def safe_unlink(path):
    temp_path = Path(path)
    for _ in range(5):
        try:
            temp_path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.2)
    print(f"Warning: could not delete temporary audio file because it is still in use: {temp_path}")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("localhost", PORT), SpeechTrainerHandler)
    print(f"Speech Trainer Python running at http://localhost:{PORT}")
    server.serve_forever()
