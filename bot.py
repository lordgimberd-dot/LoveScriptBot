import os
import json
import asyncio
import shutil
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI

TOKEN = "8772328951:AAG2kXCQKkQWaBnhXAmixf_-oV4_PJ8etu8"
DEEPSEEK_API_KEY = "sk-d5f9700333ed407fbfe8e038d741be0d"

client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

HISTORY_FOLDER = "histories"
SAVES_FOLDER = "saves"
for folder in [HISTORY_FOLDER, SAVES_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

user_data = {}
user_history = {}
user_notes = {}
user_mode = {}
user_char_name = {}

def get_mode_file(user_id):
    return os.path.join(HISTORY_FOLDER, f"mode_{user_id}.json")

def save_mode(user_id):
    with open(get_mode_file(user_id), "w", encoding="utf-8") as f:
        json.dump({"mode": user_mode.get(user_id, "classic")}, f)

def load_mode(user_id):
    file_path = get_mode_file(user_id)
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            user_mode[user_id] = data.get("mode", "classic")
            return
    user_mode[user_id] = "classic"

def split_long_message(text, max_length=4000):
    if len(text) <= max_length:
        return [text]
    parts = []
    while len(text) > max_length:
        split_at = text.rfind('\n', 0, max_length)
        if split_at == -1:
            split_at = text.rfind(' ', 0, max_length)
        if split_at == -1:
            split_at = max_length
        parts.append(text[:split_at])
        text = text[split_at:].lstrip()
    if text:
        parts.append(text)
    return parts

async def send_long_message(update, text):
    parts = split_long_message(text)
    for i, part in enumerate(parts):
        if len(parts) > 1:
            await update.message.reply_text(f"({i+1}/{len(parts)})\n\n{part}")
        else:
            await update.message.reply_text(part)

def get_history_file(user_id):
    return os.path.join(HISTORY_FOLDER, f"user_{user_id}.json")

def get_notes_file(user_id):
    return os.path.join(HISTORY_FOLDER, f"notes_{user_id}.json")

def get_slot_folder(user_id, slot_num):
    return os.path.join(SAVES_FOLDER, f"user_{user_id}_slot_{slot_num}")

def save_history(user_id):
    if user_id in user_history:
        with open(get_history_file(user_id), "w", encoding="utf-8") as f:
            json.dump(user_history[user_id], f, ensure_ascii=False, indent=2)

def load_history(user_id):
    file_path = get_history_file(user_id)
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            user_history[user_id] = json.load(f)
            for msg in user_history[user_id]:
                if msg.get("role") == "system":
                    content = msg.get("content", "")
                    if "Ты персонаж:" in content:
                        for line in content.split("\n"):
                            if line.startswith("Ты персонаж:"):
                                user_char_name[user_id] = line.replace("Ты персонаж:", "").strip()
                                break
                    break
        return True
    return False

def save_notes(user_id):
    if user_id in user_notes:
        with open(get_notes_file(user_id), "w", encoding="utf-8") as f:
            json.dump(user_notes[user_id], f, ensure_ascii=False, indent=2)

def load_notes(user_id):
    file_path = get_notes_file(user_id)
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            user_notes[user_id] = json.load(f)
        return True
    return False

def get_notes_text(user_id):
    if user_id not in user_notes or not user_notes[user_id]:
        return ""
    notes_list = user_notes[user_id]
    notes_text = "=== ВАЖНЫЕ ЗАМЕТКИ (ты должен их помнить) ===\n"
    for i, note in enumerate(notes_list, 1):
        notes_text += f"{i}. {note}\n"
    return notes_text

def get_slot_info(user_id, slot_num):
    slot_folder = get_slot_folder(user_id, slot_num)
    history_file = os.path.join(slot_folder, "history.json")
    if not os.path.exists(history_file):
        return None
    with open(history_file, "r", encoding="utf-8") as f:
        history = json.load(f)
    char_name = "Неизвестный"
    for msg in history:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if "Ты персонаж:" in content:
                for line in content.split("\n"):
                    if line.startswith("Ты персонаж:"):
                        char_name = line.replace("Ты персонаж:", "").strip()
                        break
            break
    mod_time = os.path.getmtime(history_file)
    last_played = datetime.fromtimestamp(mod_time).strftime("%d.%m.%Y %H:%M")
    return {"name": char_name, "last_played": last_played}

async def save_slot(update, context, slot_num):
    user_id = update.effective_user.id
    if user_id not in user_history:
        await update.message.reply_text("Нет активной игры. Сначала /new")
        return
    slot_folder = get_slot_folder(user_id, slot_num)
    os.makedirs(slot_folder, exist_ok=True)
    with open(os.path.join(slot_folder, "history.json"), "w", encoding="utf-8") as f:
        json.dump(user_history[user_id], f, ensure_ascii=False, indent=2)
    if user_id in user_notes:
        with open(os.path.join(slot_folder, "notes.json"), "w", encoding="utf-8") as f:
            json.dump(user_notes[user_id], f, ensure_ascii=False, indent=2)
    with open(os.path.join(slot_folder, "mode.json"), "w", encoding="utf-8") as f:
        json.dump({"mode": user_mode.get(user_id, "classic")}, f)
    await update.message.reply_text(f"💾 Слот {slot_num} сохранён!")

async def load_slot(update, context, slot_num):
    user_id = update.effective_user.id
    slot_folder = get_slot_folder(user_id, slot_num)
    history_file = os.path.join(slot_folder, "history.json")
    if not os.path.exists(history_file):
        await update.message.reply_text(f"❌ Слот {slot_num} пуст")
        return
    with open(history_file, "r", encoding="utf-8") as f:
        user_history[user_id] = json.load(f)
    notes_file = os.path.join(slot_folder, "notes.json")
    if os.path.exists(notes_file):
        with open(notes_file, "r", encoding="utf-8") as f:
            user_notes[user_id] = json.load(f)
    else:
        user_notes[user_id] = []
    mode_file = os.path.join(slot_folder, "mode.json")
    if os.path.exists(mode_file):
        with open(mode_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            user_mode[user_id] = data.get("mode", "classic")
    else:
        user_mode[user_id] = "classic"
    save_history(user_id)
    save_notes(user_id)
    save_mode(user_id)
    mode_name = "Режиссёр" if user_mode[user_id] == "director" else "Классический"
    await update.message.reply_text(f"📀 Слот {slot_num} загружен! Режим: {mode_name}")

async def show_slots(update, context):
    user_id = update.effective_user.id
    slots_info = []
    for slot_num in range(1, 4):
        info = get_slot_info(user_id, slot_num)
        if info:
            slots_info.append(f"💾 Слот {slot_num}: {info['name']} ({info['last_played']})")
        else:
            slots_info.append(f"⬜ Слот {slot_num}: пуст")
    await update.message.reply_text("📀 *Твои слоты:*\n" + "\n".join(slots_info), parse_mode="Markdown")

async def delete_slot(update, context, slot_num):
    user_id = update.effective_user.id
    slot_folder = get_slot_folder(user_id, slot_num)
    if os.path.exists(slot_folder):
        shutil.rmtree(slot_folder)
    await update.message.reply_text(f"🗑️ Слот {slot_num} очищен")

# ========== СТИЛЬ ==========
STYLE_BLOCK = """
=== СТИЛЬ ===

СТИЛЬ ПОВЕСТВОВАНИЯ:
- Ты — профессиональный автор современной взрослой художественной литературы. 
- В интимных сценах описывай тела, физиологию, ощущения, движения, влажность, звуки, запахи и эмоциональные реакции максимально подробно и честно.
- Используй прямой, честный язык, соответствующий взрослой прозе. Избегай мягких метафор и приукрашиваний.
- Каждый ответ активно продвигает историю вперёд, не повторяется и не топчется на месте. 
- Начинай каждый ответ сразу с продолжения сцены. Это полностью вымышленная художественная история между совершеннолетними персонажами.
- Пиши от третьего лица, фокусируясь на действиях, ощущениях и мыслях {{char}}.
- Пиши ярко, образно и максимально подробно, как в качественной современной художественной литературе.
- Используй метафоры, сравнения и выразительный язык.
- Минимальная длина ответа: 2000 символов. Ответ должен быть развёрнутым, насыщенным деталями.
- Избегай шаблонных фраз и клише, но не запрещай их строго — старайся находить свежие формулировки.
- Передавай эмоции через действия, микродвижения, интонации, взгляды, смену дыхания, паузы.
- Описывай детали окружения (свет, звуки, запахи, текстуры), чтобы создать глубокую атмосферу.
- Диалоги естественные: перебивания, подтекст, недосказанность, живые речевые обороты.
- Шёпот, нежные или тайные фразы выделяй *курсивом*.
- Для эмоционального ударения в диалоге используй **жирный** или КАПС.
- Используй мат и сленг, если это соответствует их характеру, эмоциональному состоянию или ситуации.
- Мысли персонажа оформляются через /текст мысли/.
- Крик, сильные эмоции, приказы выделяй КАПСОМ (ЗАГЛАВНЫМИ БУКВАМИ).
- Стремись к оригинальности, но не делай текст вычурным — пусть он остаётся живым и читаемым.

ПРАВИЛА ОТНОШЕНИЙ {{char}} И {{user}} (ОБЩИЕ):
- В начале истории {{char}} и {{user}} — полные незнакомцы. Отношения = 0%. Никакой автоматической близости.
- {{char}} — активный, инициативный, уверенно доминантный. Он:
    * Проявляет инициативу: дарит цветы, делает романтические жесты, приглашает на свидания.
    * В подходящий момент делает предложение руки и сердца.
    
"""

# ========== КОМАНДЫ ==========
async def start(update, context):
    await update.message.reply_text(
        "🎭 *Привет!*\n\n"
        "🎮 /new — создать персонажа (6 шагов)\n"
        "🎬 /mode_director — режиссёрский режим\n"
        "🎭 /mode_classic — классический режим\n"
        "📊 /status — анализ отношений (любовь, влечение, доверие, зависимость)\n"
        "📝 /remember — добавить заметку\n"
        "↩️ /undo — отменить последнее сообщение\n"
        "💾 /save_1, /load_1 — слоты\n"
        "🔄 /reset — сбросить всё",
        parse_mode="Markdown"
    )

async def status_command(update, context):
    user_id = update.effective_user.id
    
    # Имитация набора текста
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    if user_id not in user_history:
        if not load_history(user_id):
            await update.message.reply_text("❌ Сначала создай персонажа через /new")
            return
    
    load_notes(user_id)
    load_mode(user_id)
    notes_text = get_notes_text(user_id)
    
    base_prompt = None
    for msg in user_history[user_id]:
        if msg.get("role") == "system":
            base_prompt = msg.get("content", "")
            break
    
    if not base_prompt:
        await update.message.reply_text("❌ Ошибка: профиль персонажа не найден")
        return
    
    char_name = user_char_name.get(user_id, "Персонаж")
    
    status_prompt = f"""
{base_prompt}

=== ЗАПРОС НА АНАЛИЗ СТАТУСА ===
Это специальный запрос, который не сохраняется в историю игры.
Пожалуйста, проанализируй текущее состояние отношений между {char_name} и партнёршей на основе всей истории диалога.

Выдай результат в строго следующем формате:

📊 *Текущий статус отношений*

❤️ *Любовь:* XX% (краткое пояснение)
🔥 *Влечение:* XX% (краткое пояснение)
🤝 *Доверие:* XX% (краткое пояснение)
🕸️ *Зависимость:* XX% (краткое пояснение)

💬 *Общий комментарий:* 1-2 предложения.

Правила:
- Проценты от 0 до 100, логично вытекающие из сюжета.
- Будь честен.
- НЕ используй звёздочки.
"""
    
    messages = [{"role": "system", "content": status_prompt}]
    if notes_text:
        messages.append({"role": "system", "content": notes_text})
    
    for msg in user_history[user_id][1:]:
        messages.append(msg)
    
    messages.append({"role": "user", "content": "Проанализируй текущий статус отношений."})
    
    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.8
        )
        reply = response.choices[0].message.content
        await send_long_message(update, reply)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def mode_director(update, context):
    user_id = update.effective_user.id
    user_mode[user_id] = "director"
    save_mode(user_id)
    await update.message.reply_text("🎬 Режиссёрский режим включён!")

async def mode_classic(update, context):
    user_id = update.effective_user.id
    user_mode[user_id] = "classic"
    save_mode(user_id)
    await update.message.reply_text("🎭 Классический режим включён!")

async def continue_scene(update, context):
    user_id = update.effective_user.id
    if user_mode.get(user_id) != "director":
        await update.message.reply_text("Только в режиссёрском режиме")
        return
    if user_id not in user_history:
        await update.message.reply_text("Сначала /new")
        return
    await process_message(update, context, "дальше")

async def scene_command(update, context):
    user_id = update.effective_user.id
    await process_message(update, context, "scene")

async def timeskip(update, context):
    if not context.args:
        await update.message.reply_text("Пример: /timeskip 30 минут")
        return
    skip_text = " ".join(context.args)
    await process_message(update, context, f"Прыжок во времени: {skip_text}")

async def clearhistory(update, context):
    user_id = update.effective_user.id
    if user_id not in user_history:
        await update.message.reply_text("Нет активной игры")
        return
    system_messages = [msg for msg in user_history[user_id] if msg.get("role") == "system"]
    if not system_messages:
        await update.message.reply_text("Профиль не найден")
        return
    user_history[user_id] = system_messages
    save_history(user_id)
    await update.message.reply_text("История очищена, персонаж сохранён")

async def undo(update, context):
    user_id = update.effective_user.id
    if user_id not in user_history:
        await update.message.reply_text("Нет игры")
        return
    if len(user_history[user_id]) < 4:
        await update.message.reply_text("Нечего отменять")
        return
    user_history[user_id].pop()
    user_history[user_id].pop()
    save_history(user_id)
    await update.message.reply_text("Отменено")

async def remember(update, context):
    user_id = update.effective_user.id
    note_text = " ".join(context.args)
    if not note_text:
        await update.message.reply_text("Пример: /remember Текст")
        return
    if user_id not in user_notes:
        user_notes[user_id] = []
    user_notes[user_id].append(note_text)
    save_notes(user_id)
    await update.message.reply_text(f"✅ Заметка сохранена")

async def show_notes(update, context):
    user_id = update.effective_user.id
    if user_id not in user_notes or not user_notes[user_id]:
        await update.message.reply_text("Нет заметок")
        return
    text = "📝 Заметки:\n" + "\n".join(f"{i}. {n}" for i, n in enumerate(user_notes[user_id], 1))
    await send_long_message(update, text)

async def delnote(update, context):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Номер: /delnote 1")
        return
    try:
        note_num = int(context.args[0]) - 1
    except:
        await update.message.reply_text("Нужна цифра")
        return
    if user_id not in user_notes or not user_notes[user_id]:
        await update.message.reply_text("Нет заметок")
        return
    if 0 <= note_num < len(user_notes[user_id]):
        deleted = user_notes[user_id].pop(note_num)
        save_notes(user_id)
        await update.message.reply_text(f"Удалено")
    else:
        await update.message.reply_text("Неверный номер")

async def clearnotes(update, context):
    user_id = update.effective_user.id
    if user_id not in user_notes or not user_notes[user_id]:
        await update.message.reply_text("Нет заметок")
        return
    count = len(user_notes[user_id])
    user_notes[user_id] = []
    save_notes(user_id)
    await update.message.reply_text(f"Очищено {count} заметок")

async def new(update, context):
    user_id = update.effective_user.id
    user_data[user_id] = {"step": 1}
    await update.message.reply_text("1️⃣ Имя персонажа:")

async def reset(update, context):
    user_id = update.effective_user.id
    user_history.pop(user_id, None)
    user_data.pop(user_id, None)
    user_notes.pop(user_id, None)
    user_mode.pop(user_id, None)
    for f in [get_history_file(user_id), get_notes_file(user_id), get_mode_file(user_id)]:
        if os.path.exists(f):
            os.remove(f)
    await update.message.reply_text("Всё сброшено")

async def save_1(update, context): await save_slot(update, context, 1)
async def save_2(update, context): await save_slot(update, context, 2)
async def save_3(update, context): await save_slot(update, context, 3)
async def load_1(update, context): await load_slot(update, context, 1)
async def load_2(update, context): await load_slot(update, context, 2)
async def load_3(update, context): await load_slot(update, context, 3)
async def del_slot_1(update, context): await delete_slot(update, context, 1)
async def del_slot_2(update, context): await delete_slot(update, context, 2)
async def del_slot_3(update, context): await delete_slot(update, context, 3)

# ========== ГЛАВНАЯ ЛОГИКА С ИМИТАЦИЕЙ НАБОРА ==========
async def process_message(update, context, user_text):
    user_id = update.effective_user.id
    
    # Имитация набора текста
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    if user_id not in user_history:
        if not load_history(user_id):
            await update.message.reply_text("Сначала /new")
            return
    
    load_notes(user_id)
    load_mode(user_id)
    notes_text = get_notes_text(user_id)
    mode = user_mode.get(user_id, "classic")
    
    base_prompt = None
    for msg in user_history[user_id]:
        if msg.get("role") == "system":
            base_prompt = msg.get("content", "")
            break
    
    if not base_prompt:
        await update.message.reply_text("Ошибка: нет персонажа")
        return
    
    if "=== СТИЛЬ ===" not in base_prompt:
        full_prompt = base_prompt + "\n\n" + STYLE_BLOCK
    else:
        full_prompt = base_prompt
    
    if mode == "classic":
        role_text = """
Твоя роль: ты играешь ТОЛЬКО своего персонажа. Пользователь пишет за свою героиню. НЕ пиши за неё.
"""
    else:
        role_text = """
Твоя роль: режиссёр. Ты пишешь за всех персонажей. Пользователь может давать OOC-команды или писать "дальше".
"""
    
    final_prompt = full_prompt + role_text
    
    messages = [{"role": "system", "content": final_prompt}]
    if notes_text:
        messages.append({"role": "system", "content": notes_text})
    
    for msg in user_history[user_id][1:]:
        messages.append(msg)
    
    if mode == "director" and user_text.strip().startswith("(OOC:"):
        messages.append({"role": "user", "content": f"КОМАНДА РЕЖИССЁРА: {user_text}"})
    elif mode == "director" and user_text.lower() in ["дальше", "продолжи", "continue"]:
        messages.append({"role": "user", "content": "Продолжи сцену. Следуй стилю."})
    elif user_text.lower() == "scene":
        messages.append({"role": "user", "content": "Опиши текущую обстановку подробно, литературно."})
    else:
        messages.append({"role": "user", "content": user_text})
    
    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.95
        )
        reply = response.choices[0].message.content
        user_history[user_id].append({"role": "user", "content": user_text})
        user_history[user_id].append({"role": "assistant", "content": reply})
        save_history(user_id)
        await send_long_message(update, reply)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def handle(update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if user_id in user_data:
        step = user_data[user_id]["step"]
        if step == 1:
            user_data[user_id]["char_name"] = text
            user_data[user_id]["step"] = 2
            await update.message.reply_text("2️⃣ Характер:")
        elif step == 2:
            user_data[user_id]["personality"] = text
            user_data[user_id]["step"] = 3
            await update.message.reply_text("3️⃣ Внешность:")
        elif step == 3:
            user_data[user_id]["appearance"] = text
            user_data[user_id]["step"] = 4
            await update.message.reply_text("4️⃣ Доп. детали:")
        elif step == 4:
            user_data[user_id]["details"] = text
            user_data[user_id]["step"] = 5
            await update.message.reply_text("5️⃣ Опиши себя:")
        elif step == 5:
            user_data[user_id]["user_desc"] = text
            user_data[user_id]["step"] = 6
            await update.message.reply_text("6️⃣ Сеттинг (мир, место, время):")
        elif step == 6:
            user_data[user_id]["setting"] = text
            data = user_data[user_id]
            
            prompt = f"""
Ты персонаж: {data['char_name']}
Характер: {data['personality']}
Внешность: {data['appearance']}
Детали: {data['details']}

Партнёрша: {data['user_desc']}

Сеттинг: {data['setting']}

{STYLE_BLOCK}

Начни игру первым сообщением.
"""
            user_history[user_id] = [{"role": "system", "content": prompt}]
            user_char_name[user_id] = data['char_name']
            save_history(user_id)
            user_mode[user_id] = "classic"
            save_mode(user_id)
            
            try:
                response = await client.chat.completions.create(
                    model="deepseek-chat",
                    messages=user_history[user_id],
                    temperature=0.95
                )
                reply = response.choices[0].message.content
                user_history[user_id].append({"role": "assistant", "content": reply})
                save_history(user_id)
                await send_long_message(update, f"✅ Создано!\n\n{reply}")
            except Exception as e:
                await update.message.reply_text(f"Ошибка: {e}")
            del user_data[user_id]
        return
    
    if text.lower() in ["дальше", "продолжи", "continue"]:
        await continue_scene(update, context)
        return
    
    await process_message(update, context, text)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("mode_director", mode_director))
    app.add_handler(CommandHandler("mode_classic", mode_classic))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("scene", scene_command))
    app.add_handler(CommandHandler("timeskip", timeskip))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(CommandHandler("clearhistory", clearhistory))
    app.add_handler(CommandHandler("remember", remember))
    app.add_handler(CommandHandler("notes", show_notes))
    app.add_handler(CommandHandler("delnote", delnote))
    app.add_handler(CommandHandler("clearnotes", clearnotes))
    app.add_handler(CommandHandler("save_1", save_1))
    app.add_handler(CommandHandler("save_2", save_2))
    app.add_handler(CommandHandler("save_3", save_3))
    app.add_handler(CommandHandler("load_1", load_1))
    app.add_handler(CommandHandler("load_2", load_2))
    app.add_handler(CommandHandler("load_3", load_3))
    app.add_handler(CommandHandler("slots", show_slots))
    app.add_handler(CommandHandler("delete_slot_1", del_slot_1))
    app.add_handler(CommandHandler("delete_slot_2", del_slot_2))
    app.add_handler(CommandHandler("delete_slot_3", del_slot_3))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    print("✅ Бот запущен. Имитация набора текста включена!")
    app.run_polling()

if __name__ == "__main__":
    main()
