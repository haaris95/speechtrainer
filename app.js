let questions = [];
const TOTAL_QUESTIONS = 5;

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition;
let mediaStream;
let audioContext;
let audioSource;
let audioProcessor;
let wavSamples = [];
let recordingStartedAt = 0;
let recordingSampleRate = 44100;
let currentIndex = -1;
let isRecording = false;
const answers = [];
const answerReports = [];

const startTest = document.querySelector("#startTest");
const recordButton = document.querySelector("#recordButton");
const nextQuestion = document.querySelector("#nextQuestion");
const scoreTest = document.querySelector("#scoreTest");
const questionText = document.querySelector("#questionText");
const questionHint = document.querySelector("#questionHint");
const partLabel = document.querySelector("#partLabel");
const sectionTitle = document.querySelector("#sectionTitle");
const transcriptText = document.querySelector("#transcriptText");
const speechStatus = document.querySelector("#speechStatus");
const questionList = document.querySelector("#questionList");
const progressFill = document.querySelector("#progressFill");
const introScreen = document.querySelector("#introScreen");
const testScreen = document.querySelector("#testScreen");
const resultScreen = document.querySelector("#resultScreen");
const questionCounter = document.querySelector("#questionCounter");
const resultStatus = document.querySelector("#resultStatus");

startTest.addEventListener("click", startMockTest);
recordButton.addEventListener("click", toggleRecording);
nextQuestion.addEventListener("click", goToNextQuestion);
scoreTest.addEventListener("click", scoreSpeaking);

setupSpeechRecognition();

function setupSpeechRecognition() {
  if (!SpeechRecognition) {
    speechStatus.textContent = "Speech recognition is not supported in this browser";
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.interimResults = true;
  recognition.continuous = true;

  recognition.addEventListener("result", (event) => {
    let finalText = answers[currentIndex]?.transcript || "";
    let interimText = "";

    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const transcript = event.results[index][0].transcript;
      if (event.results[index].isFinal) {
        finalText = `${finalText} ${transcript}`.trim();
      } else {
        interimText = transcript;
      }
    }

    answers[currentIndex].transcript = finalText;
    transcriptText.textContent = `${finalText}${interimText ? `\n\n${interimText}` : ""}` || "Listening...";
    scoreTest.disabled = !answers.some((answer) => answer.transcript.trim());
  });

  recognition.addEventListener("end", () => {
    if (!isRecording) {
      speechStatus.textContent = "Microphone idle";
    }
  });
}

function renderQuestionList() {
  questionList.innerHTML = "";
  Array.from({ length: TOTAL_QUESTIONS }).forEach((_, index) => {
    const item = document.createElement("li");
    item.textContent = `Question ${index + 1}`;
    if (index === currentIndex) item.classList.add("active");
    questionList.append(item);
  });
}

async function startMockTest() {
  startTest.disabled = true;
  startTest.textContent = "Preparing first question...";
  currentIndex = 0;
  questions = [];
  answers.length = 0;
  answerReports.length = 0;
  const firstQuestion = await fetchNextQuestion().catch((error) => {
    showQuestionLoadError(error.message);
    return null;
  });
  if (!firstQuestion) {
    startTest.textContent = "Try Again";
    startTest.disabled = false;
    return;
  }
  questions.push(firstQuestion);
  answers.push(createEmptyAnswer(firstQuestion));
  startTest.textContent = "Restart Mock Test";
  startTest.disabled = false;
  showScreen(testScreen);
  recordButton.disabled = !navigator.mediaDevices?.getUserMedia;
  nextQuestion.disabled = false;
  scoreTest.disabled = true;
  showQuestion();
}

function createEmptyAnswer(question) {
  return {
    question,
    transcript: "",
    audioBlob: null,
    audioDataUrl: "",
    durationSeconds: 0,
  };
}

async function fetchNextQuestion() {
  if (location.protocol === "file:") {
    throw new Error("Open the app through http://localhost:8789, not file://.");
  }
  const response = await fetch("/api/generate-question", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      questionIndex: currentIndex,
      totalQuestions: TOTAL_QUESTIONS,
      targetBand: "6.5",
      topicPreference: "general IELTS speaking topics",
      previousQuestions: questions.map((question) => question.text),
      previousAnswerSummaries: answerReports.map((report) => ({
        question: report.question,
        estimatedBand: report.estimatedBand,
        strength: report.strength,
        improvement: report.improvement,
      })),
    }),
  });
  if (!response.ok) {
    const errorPayload = await response.json().catch(() => ({}));
    throw new Error(errorPayload.message || "AI question generation failed.");
  }
  const payload = await response.json();
  return validateQuestion(payload.question);
}

function validateQuestion(question) {
  if (!question || typeof question !== "object") {
    throw new Error("AI did not return a valid IELTS question.");
  }
  return {
    part: requireQuestionField(question.part, currentIndex, "part"),
    title: requireQuestionField(question.title, currentIndex, "title"),
    text: requireQuestionField(question.text, currentIndex, "text"),
    hint: requireQuestionField(question.hint, currentIndex, "hint"),
  };
}

function requireQuestionField(value, index, fieldName) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    throw new Error(`AI question ${index + 1} is missing ${fieldName}.`);
  }
  return normalized;
}

function showQuestionLoadError(message) {
  showScreen(introScreen);
  const introCopy = document.querySelector(".intro-copy");
  let errorBox = document.querySelector("#questionLoadError");
  if (!errorBox) {
    errorBox = document.createElement("p");
    errorBox.id = "questionLoadError";
    errorBox.className = "error-message";
    introCopy.append(errorBox);
  }
  errorBox.textContent = message;
}

function showQuestion() {
  const question = questions[currentIndex];
  partLabel.textContent = question.part;
  sectionTitle.textContent = question.title;
  questionCounter.textContent = `Question ${currentIndex + 1} of ${TOTAL_QUESTIONS}`;
  questionText.textContent = question.text;
  questionHint.textContent = question.hint;
  transcriptText.textContent = answers[currentIndex].transcript || "Press Record Answer and start speaking.";
  nextQuestion.textContent = currentIndex === TOTAL_QUESTIONS - 1 ? "Finish & View Results" : "Next Question";
  progressFill.style.width = `${((currentIndex + 1) / TOTAL_QUESTIONS) * 100}%`;
  renderQuestionList();
}

async function toggleRecording() {
  if (currentIndex < 0) return;

  if (isRecording) {
    stopRecording();
    return;
  }

  await startRecording();
}

async function startRecording() {
  mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  audioContext = new AudioContext();
  recordingSampleRate = audioContext.sampleRate;
  audioSource = audioContext.createMediaStreamSource(mediaStream);
  audioProcessor = audioContext.createScriptProcessor(4096, 1, 1);
  wavSamples = [];
  recordingStartedAt = performance.now();
  isRecording = true;
  recordButton.classList.add("recording");
  recordButton.innerHTML = "<span></span> Stop Recording";
  speechStatus.textContent = "Recording audio...";

  audioProcessor.onaudioprocess = (event) => {
    wavSamples.push(new Float32Array(event.inputBuffer.getChannelData(0)));
  };
  audioSource.connect(audioProcessor);
  audioProcessor.connect(audioContext.destination);

  if (recognition) {
    try {
      recognition.start();
    } catch {
      // Speech recognition can throw if it is already active; audio capture is the source of truth.
    }
  }
}

async function stopRecording() {
  isRecording = false;
  recordButton.classList.remove("recording");
  recordButton.innerHTML = "<span></span> Record Answer";
  speechStatus.textContent = "Processing audio...";

  if (recognition) recognition.stop();
  audioProcessor?.disconnect();
  audioSource?.disconnect();
  mediaStream?.getTracks().forEach((track) => track.stop());
  await audioContext?.close();

  const audioBlob = encodeWav(wavSamples, recordingSampleRate);
  answers[currentIndex].audioBlob = audioBlob;
  answers[currentIndex].audioDataUrl = await blobToDataUrl(audioBlob);
  answers[currentIndex].durationSeconds = Math.round((performance.now() - recordingStartedAt) / 1000);
  scoreTest.disabled = !answers.some((answer) => answer.audioBlob);
  speechStatus.textContent = `WAV audio captured: ${answers[currentIndex].durationSeconds}s`;
}

async function goToNextQuestion() {
  if (isRecording) await stopRecording();
  const currentAnswer = answers[currentIndex];
  if (!currentAnswer?.audioDataUrl) {
    speechStatus.textContent = "Record an answer before moving to the next question.";
    return;
  }

  nextQuestion.disabled = true;
  recordButton.disabled = true;
  speechStatus.textContent = "Processing this answer privately...";
  const answerReport = await evaluateCurrentAnswer(currentAnswer).catch((error) => {
    speechStatus.textContent = error.message || "Could not process this answer.";
    nextQuestion.disabled = false;
    recordButton.disabled = false;
    return null;
  });
  if (!answerReport) return;
  answerReports[currentIndex] = answerReport;

  if (currentIndex < TOTAL_QUESTIONS - 1) {
    currentIndex += 1;
    speechStatus.textContent = "Fetching the next AI question...";
    const nextAiQuestion = await fetchNextQuestion().catch((error) => {
      speechStatus.textContent = error.message || "Could not fetch the next question.";
      return null;
    });
    if (!nextAiQuestion) {
      currentIndex -= 1;
      nextQuestion.disabled = false;
      recordButton.disabled = false;
      return;
    }
    questions[currentIndex] = nextAiQuestion;
    answers[currentIndex] = createEmptyAnswer(nextAiQuestion);
    recordButton.disabled = !navigator.mediaDevices?.getUserMedia;
    nextQuestion.disabled = false;
    showQuestion();
    return;
  }

  await scoreSpeaking();
}

async function evaluateCurrentAnswer(answer) {
  if (location.protocol === "file:") {
    throw new Error("Open the app through http://localhost:8789, not file://.");
  }
  const response = await fetch("/api/evaluate-answer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      answer: {
        question: answer.question.text,
        part: answer.question.part,
        transcript: answer.transcript,
        audioDataUrl: answer.audioDataUrl,
        durationSeconds: answer.durationSeconds,
      },
    }),
  });
  if (!response.ok) {
    const errorPayload = await response.json().catch(() => ({}));
    throw new Error(errorPayload.message || "Answer evaluation failed.");
  }
  return response.json();
}

async function scoreSpeaking() {
  showResultLoading();
  const apiResult = await fetchFinalReport().catch((error) => {
    resultStatus.textContent = error.message || "Final report generation failed.";
    document.querySelector("#feedbackList").innerHTML =
      "<p>The interview was completed, but the AI report could not be generated. Check server logs and credentials.</p>";
    return null;
  });
  if (apiResult) renderApiScore(apiResult);
}

async function evaluateAudioWithBackend() {
  if (location.protocol === "file:") return null;
  const response = await fetch("/api/evaluate-speaking", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      answers: answers
        .filter((answer) => answer.audioDataUrl)
        .map((answer) => ({
          question: answer.question.text,
          part: answer.question.part,
          transcript: answer.transcript,
          audioDataUrl: answer.audioDataUrl,
          durationSeconds: answer.durationSeconds,
        })),
    }),
  });

  if (!response.ok) return null;
  return response.json();
}

async function fetchFinalReport() {
  if (location.protocol === "file:") return null;
  const response = await fetch("/api/final-report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      answerReports,
    }),
  });

  if (!response.ok) {
    const errorPayload = await response.json().catch(() => ({}));
    throw new Error(errorPayload.message || "Final report generation failed.");
  }
  return response.json();
}

function renderApiScore(result) {
  showScreen(resultScreen);
  resultStatus.textContent = "Azure Speech metrics and Foundry coaching report generated.";
  document.querySelector("#bandScore").textContent = Number(result.overallBand).toFixed(1);
  document.querySelector("#fluencyScore").textContent = Number(result.fluencyBand).toFixed(1);
  document.querySelector("#pronunciationScore").textContent = Number(result.pronunciationBand).toFixed(1);
  document.querySelector("#vocabScore").textContent = Number(result.vocabularyBand).toFixed(1);
  document.querySelector("#grammarScore").textContent = Number(result.grammarBand).toFixed(1);
  const breakdown = result.answerBreakdown || [];
  document.querySelector("#feedbackList").innerHTML = [
    ...(result.feedback || []),
    ...breakdown.map((item) => `${item.question}: ${item.strength} Improve by ${item.improvement}`),
  ]
    .map((item) => `<article>${escapeHtml(item)}</article>`)
    .join("");
}

function showResultLoading() {
  showScreen(resultScreen);
  resultStatus.textContent = "Analyzing audio, pronunciation, transcript, and IELTS criteria...";
  document.querySelector("#bandScore").textContent = "--";
  document.querySelector("#fluencyScore").textContent = "--";
  document.querySelector("#pronunciationScore").textContent = "--";
  document.querySelector("#vocabScore").textContent = "--";
  document.querySelector("#grammarScore").textContent = "--";
  document.querySelector("#feedbackList").innerHTML = "<p>Preparing your professional feedback report...</p>";
}

function showScreen(screen) {
  [introScreen, testScreen, resultScreen].forEach((candidate) => candidate.classList.remove("is-active"));
  screen.classList.add("is-active");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function estimateComplexity(text) {
  const connectors = ["because", "although", "however", "therefore", "while", "whereas", "for example"];
  const lower = text.toLowerCase();
  const connectorHits = connectors.filter((connector) => lower.includes(connector)).length;
  const sentenceCount = Math.max(1, (text.match(/[.!?]/g) || []).length);
  const wordCount = (text.match(/\b[\w']+\b/g) || []).length;
  return Math.min(2, connectorHits * 0.25 + wordCount / sentenceCount / 28);
}

function renderFeedback({ fluency, vocabulary, grammar, averageWords, answeredCount, wordsPerMinute }) {
  const feedback = [];

  if (answeredCount < TOTAL_QUESTIONS) {
    feedback.push("Answer every question. IELTS examiners need enough language to judge your range.");
  }
  if (!location.protocol.startsWith("http")) {
    feedback.push("Audio was captured locally. Run the backend to send full audio for pronunciation, prosody, and pause analysis.");
  }
  if (wordsPerMinute && (wordsPerMinute < 85 || wordsPerMinute > 170)) {
    feedback.push("Your estimated speaking pace may need work. IELTS fluency improves when speech is steady, not too slow or rushed.");
  }
  if (averageWords < 45) {
    feedback.push("Extend your answers with a reason, example, and short conclusion.");
  } else {
    feedback.push("Good answer length. Keep organizing responses with clear examples.");
  }
  if (vocabulary < 6) {
    feedback.push("Use more topic-specific vocabulary and avoid repeating the same simple words.");
  }
  if (grammar < 6) {
    feedback.push("Add complex sentences using because, although, while, and for example.");
  }
  if (fluency >= 6 && vocabulary >= 6 && grammar >= 6) {
    feedback.push("Strong practice attempt. Next, focus on smoother transitions and natural pronunciation.");
  }

  document.querySelector("#feedbackList").innerHTML = feedback
    .map((item) => `<article>${escapeHtml(item)}</article>`)
    .join("");
}

function clampScore(score) {
  return roundHalf(Math.max(3, Math.min(8.5, score)));
}

function roundHalf(score) {
  return Math.round(score * 2) / 2;
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(reader.result));
    reader.addEventListener("error", reject);
    reader.readAsDataURL(blob);
  });
}

function encodeWav(channelBuffers, sampleRate) {
  const sampleCount = channelBuffers.reduce((total, buffer) => total + buffer.length, 0);
  const dataSize = sampleCount * 2;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  let offset = 0;

  writeString(view, offset, "RIFF");
  offset += 4;
  view.setUint32(offset, 36 + dataSize, true);
  offset += 4;
  writeString(view, offset, "WAVE");
  offset += 4;
  writeString(view, offset, "fmt ");
  offset += 4;
  view.setUint32(offset, 16, true);
  offset += 4;
  view.setUint16(offset, 1, true);
  offset += 2;
  view.setUint16(offset, 1, true);
  offset += 2;
  view.setUint32(offset, sampleRate, true);
  offset += 4;
  view.setUint32(offset, sampleRate * 2, true);
  offset += 4;
  view.setUint16(offset, 2, true);
  offset += 2;
  view.setUint16(offset, 16, true);
  offset += 2;
  writeString(view, offset, "data");
  offset += 4;
  view.setUint32(offset, dataSize, true);
  offset += 4;

  channelBuffers.forEach((samples) => {
    samples.forEach((sample) => {
      const clipped = Math.max(-1, Math.min(1, sample));
      view.setInt16(offset, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true);
      offset += 2;
    });
  });

  return new Blob([buffer], { type: "audio/wav" });
}

function writeString(view, offset, value) {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index));
  }
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
