import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.154/build/three.module.js';
import { GLTFLoader } from 'https://cdn.jsdelivr.net/npm/three@0.154/examples/jsm/loaders/GLTFLoader.js';

let username = "";

document.getElementById("login-btn").onclick = async () => {
  username = document.getElementById("username").value.trim();
  if (!username) return alert("Enter your name.");

  const res = await fetch("http://localhost:5000/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username })
  });

  const data = await res.json();
  if (data.message) {
    localStorage.setItem("username", username);
    document.getElementById("login-section").style.display = "none";
    document.getElementById("main-container").style.display = "flex";
    loadAvatar(username);
  }
};

function loadAvatar(user) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(25, 1, 0.1, 1000);
  camera.position.z = 2;
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(500, 500);
  document.getElementById("avatar-canvas").appendChild(renderer.domElement);

  const loader = new GLTFLoader();
  const avatarURL = `https://models.readyplayer.me/${user}.glb`;
  loader.load(avatarURL, gltf => {
    const model = gltf.scene;
    model.scale.set(1.5, 1.5, 1.5);
    scene.add(model);
    animate();
    function animate() {
      requestAnimationFrame(animate);
      renderer.render(scene, camera);
    }
  });
}

document.getElementById("chat-form").onsubmit = async (e) => {
  e.preventDefault();
  const input = document.getElementById("user-input").value;
  displayUserMessage(input);
  document.getElementById("user-input").value = "";

  const res = await fetch("http://localhost:5000/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: input })
  });

  const data = await res.json();
  displayBotMessage(data.response);
  speak(data.response);
};

function displayUserMessage(msg) {
  const el = document.createElement("div");
  el.className = "user-msg";
  el.innerText = msg;
  document.getElementById("chat-log").appendChild(el);
}

function displayBotMessage(msg) {
  const el = document.createElement("div");
  el.className = "bot-msg";
  el.innerText = msg;
  document.getElementById("chat-log").appendChild(el);
}

function speak(text) {
  const utterance = new SpeechSynthesisUtterance(text);
  speechSynthesis.speak(utterance);
}