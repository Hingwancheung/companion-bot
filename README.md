# Companion Bot

*Companion Bot is a Python-based chatbot designed for long-term, personalized conversation.
It features multi-provider language-model switching, a long-term memory system, vision understanding, and a set of tunable behavioral parameters.
The architecture is modular, easy to maintain, and friendly to customizing personality prompts and behaviors.

This project is ideal for:
	•	developers who want to self-host an AI companion, assistant, or role-play bot
	•	researchers interested in multi-model routing and failover logic
	•	users who want to build a chatbot with a persistent long-term memory system*

---

## Languages

- [English](#english-readme)
- [繁體中文](#中文說明-readme)

---

# English README

## ✉️ Message Handling & Scheduling

- **Segmented message sending**  
  Long model replies are automatically split into multiple Telegram messages.

- **Time-aware responses**  
  The bot recognizes local timezone settings and adjusts behavior accordingly.

- **Scheduled proactive messages**  
  Periodic check-ins or reminders via configurable timers.

- **Customizable quiet hours**  
  A fully user-defined Do-Not-Disturb period (e.g., 23:00–08:00) during which the bot pauses outgoing nudges and reminders.

---

## 🤖 Multi-Provider LLM Routing

- **Automatic provider rotation**  
  When a provider’s key is exhausted or fails, the bot switches to the next available provider.

- **Supports both key rotation and vendor rotation**  
  Seamlessly switches between multiple API keys *and* multiple model providers.

- **Separate models for chat, memory, and vision**  
  - Chat runs on the primary multi-provider stack  
  - Long-term memory summaries can use a dedicated `MEMORY_MODEL`  
  - Image understanding runs on its own `VISION_MODEL`

- **Primary → fallback routing logic**  
  A prioritized provider order with automatic failover.

- **Cooldown system**  
  Failed providers enter a cooldown period before being retried.

- **Per-provider configurable parameters**  
  Temperature, max tokens, model name, timeout, etc., are all independently adjustable via `.env`.

---

## 🧠 Memory & Logging System

- **Full conversation logging**  
  All incoming/outgoing messages can be stored in `chat_today.txt`.

- **Sliding-window summarization**  
  When the chat buffer reaches a configurable line limit, the bot generates a summary block and appends it to `memory.txt`, keeping daily logs lightweight.

- **Importance-scored memories**  
  Each memory entry is tagged with an importance level (1–5) for future selective use.

- **Self-clearing daily logs**  
  After summarization, the daily chat file can be reset automatically.

- **Manual memory & prompt editing**  
  All memory, summaries, and prompts are human-editable for fine-tuning personality or behavior.

- **Customizable diary format**  
  You can define your preferred summary length or diary structure.

---

## 👁️ Vision

- **Pluggable OpenAI-compatible vision backend**  
  Uses a configurable base URL, model name, and API key.

- **Image-to-text descriptions**  
  Converts images into detailed textual descriptions before handing them to the main LLM.

---

## 🛠️ System Utilities & Developer Tools

- **One-click `botchk` status diagnostic**  
  Runs a quick internal check to inspect provider availability, cooldown status, memory size, and current model.

- **Persistent runtime state**  
  `state.json` stores last user activity and last nudge timestamps so behavior survives restarts.

- **Debug switch (`_dbg()`)**  
  A global on/off flag enabling verbose diagnostics for testing.

- **Configuration via `.env` only**  
  All operational parameters can be tuned without touching the codebase.

---

## 🗂 Project Structure

```text
companion-bot/
├── bot.py             # Main Telegram event loop & routing
├── providers.py       # Multi-provider LLM routing logic
├── memory.py          # Long-term memory summarization & storage
├── vision_provider.py # Vision backend wrapper
├── character.txt      # Personality prompt
├── style.txt          # Style / tone prompt
├── state.json         # Persistent runtime state (timestamps, etc.)
├── .env.example       # Configuration template
├── .gitignore
└── data/              # Runtime data (created automatically)
    ├── chat_today.txt # Daily conversation log (optional)
    └── memory.txt     # Long-term memory store
```
---

## ⚙️ Configuration

### 1. Create .env
Copy the example file:
cp .env.example .env
Fill in your own API keys and configuration.

### 2. Run the Bot
Inside your virtual environment:
python bot.py

---
   
## 🥰 Final Words

If this little bot ever keeps you company on a quiet, sleepless night,
then that is probably the most important reason I built this project.

Thank you for reading — and for using it. ❣️


---

# 中文說明 README

## 🌟 專案介紹

Companion Bot 是一個使用 Python 撰寫的 Telegram 情感陪伴型 AI Bot。  
它具有多供應商語言模型切換、長期記憶系統、影像理解、可調式行為參數等功能。  
整體架構模組化、易於維護，也便於自訂個性化行為與提示詞。

本專案適合：
- 想自架 AI 夥伴、助理或角色扮演 Bot 的開發者
- 想瞭解多模型切換與故障轉移（failover）邏輯的研究者
- 想製作有「記憶系統」的聊天機器人的使用者

---

## ✉️ 訊息處理與排程系統

- **長訊息自動分段**  
  生成訊息過長時會自動切分，多次傳送讓閱讀更順暢。

- **具備時間感知行為**  
  Bot 能根據設定的時區調整行為邏輯。

- **定時主動訊息（Nudge）**  
  若使用者長時間未互動，Bot 可在自訂的間隔內主動發送一句話。

- **可自訂「免打擾」時段**  
  在指定時段內（如 23:00–08:00），Bot 會自動停止主動訊息與提醒。

---

## 🤖 多模型供應商（LLM）路由系統

- **自動切換 API Key 與供應商**  
  當某個 Key 用完、失敗或超時時，Bot 會自動切換到下一個 Key 或下一家供應商。

- **支援「主模型 → 備用模型」降級邏輯**  
  可設定多層級模型順序，有效避免 API 中斷導致服務停止。

- **聊天、記憶、影像可使用不同模型**  
  - 日常聊天：走主要的多供應商路由  
  - 長期記憶整理：可以指定獨立 `MEMORY_MODEL`  
  - 影像描述：使用獨立的 `VISION_MODEL`

- **冷卻系統（Cooldown）**  
  失敗的供應商會進入冷卻時間，不會被立即重試。

- **可獨立設定參數**  
  溫度（temperature）、最大回覆長度、模型名稱、超時時間等皆可在 `.env` 中調整。

---

## 🧠 記憶與對話記錄系統

- **完整對話記錄至 `chat_today.txt`**  
  所有對話都會保存於每日檔案。

- **自動摘要（Sliding Window Summarization）**  
  當對話達到某個行數後，Bot 會產生一段記憶摘要並寫入 `memory.txt`。

- **記憶條目具有重要度（1–5）**  
  用於標記該段對話在長期記憶中的權重。

- **每日對話自動清空**  
  摘要完成後會清除舊對話，避免檔案膨脹。

- **人工可編輯的提示詞與記憶**  
  包含人格、風格、記憶檔案皆允許手動微調。

- **可自訂日記摘要字數或格式**  
  有助於創造更貼近使用者需求的個性化人格模型。

---

## 👁️ 影像理解（Vision）

- **可替換的 OpenAI-Compatible Vision Backend**  
  支援自訂 API Base URL、Model 名稱與金鑰。

- **影像 → 文字描述**  
  Bot 會先將圖片轉成詳細文字，再交由聊天模型處理。

---

## 🛠️ 開發者工具與系統功能

- **一鍵 `botchk` 系統檢查**  
  可快速檢查：模型可用性、冷卻狀態、記憶容量、當前使用模型等。

- **持久化狀態（`state.json`）**  
  儲存上次互動時間與 Nudge 時戳，即使重啟服務也不會亂序。

- **Debug 模式 (`_dbg()`)**  
  可在 `.env` 中開關，輸出詳細診斷資訊。

- **所有行為均由 `.env` 控制**  
  包含：
  - 溫度  
  - 回覆長度  
  - 免打擾時段  
  - 記憶摘要長度  
  - 模型超時  
  - Provider 排序與冷卻  

  使用者不需修改程式碼即可調整 Bot 行為。

---

## 🗂 專案結構 (Project Structure)

```text
companion-bot/
├── bot.py             # 主邏輯：Telegram 事件與流程
├── providers.py       # 多供應商路由邏輯
├── memory.py          # 長期記憶系統
├── vision_provider.py # 影像模型呼叫
├── character.txt      # 人格提示詞
├── style.txt          # 回應風格提示詞
├── state.json         # 持久化狀態
├── .env.example       # 設定範本
├── .gitignore
└── data/              # 執行時自動產生的資料
    ├── chat_today.txt # 當日對話記錄
    └── memory.txt     # 長期記憶儲存
```

---

## ⚙️ 使用方法

### 1. 建立 `.env`
複製範本：
cp .env.example .env
填入您的key與設定。

### 2. 執行 Bot
在虛擬環境中：
python bot.py

---

## 🥰最後

如果這個小機器人在某個深夜曾經陪您聊過天，  
那大概就是我寫下這個專案最重要的理由。

感謝您的閱讀與使用。❣️
