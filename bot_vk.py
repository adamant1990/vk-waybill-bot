import sqlite3
import time
from datetime import datetime
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id
import signal
import sys
import os
import fcntl

# ========== ЗАЩИТА ОТ ДВОЙНОГО ЗАПУСКА ==========
def check_single_instance():
    """Проверяет, что запущен только один экземпляр бота"""
    lock_file = '/home/super/vk-waybill-bot/bot.lock'
    
    try:
        fp = open(lock_file, 'w')
        fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fp.write(str(os.getpid()))
        fp.flush()
        return fp
    except IOError:
        print("❌ Бот уже запущен! Если это не так, удалите файл bot.lock")
        try:
            with open(lock_file, 'r') as f:
                old_pid = f.read().strip()
            print(f"   Запущенный процесс PID: {old_pid}")
        except:
            pass
        sys.exit(1)

lock_fp = check_single_instance()

# ========== НАСТРОЙКИ ==========
VK_TOKEN = "vk1.a.iKPy742qB3R9M6tWvmRgk0BuyR2JO36Lp4UZkM0pVH-KmBbL5OLQoYgxTjommXbfDtsfHEIh6tWltbqydzkiefVFD-jy8QYSO6Y1Si7VpjhDziFcHEHRazAA1hsLg8ACIpQyzdIPlNouWhPEYQZbeV4_CBagFwGAZ5MprVRBmfowvHb9Ma8_MgvgeacK42IbO8c4uyJhXA2QirX-cGrG5A"
VK_GROUP_ID = 240344015
ADMIN_IDS = [1121983645]
PRICE_PER_SHIFT = 5
START_BALANCE = 500  # Начальный баланс для новых водителей

# ========== БАЗА ДАННЫХ ==========
conn = sqlite3.connect("waybills.db", check_same_thread=False)
cursor = conn.cursor()

# Создание всех таблиц
cursor.execute("""
CREATE TABLE IF NOT EXISTS cars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    norm_highway REAL DEFAULT 12.0,
    norm_city REAL DEFAULT 15.0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS drivers (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance REAL DEFAULT 500,
    is_blocked INTEGER DEFAULT 0,
    rate_per_shift REAL DEFAULT 5,
    selected_car TEXT DEFAULT 'Газель',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    car_name TEXT,
    start_mileage REAL,
    start_fuel REAL,
    total_highway REAL DEFAULT 0,
    total_city REAL DEFAULT 0,
    total_refueled REAL DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    was_paid INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    highway REAL,
    city REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    admin_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Добавляем начальные данные
cursor.execute("INSERT OR IGNORE INTO cars (name, norm_highway, norm_city) VALUES (?, ?, ?)", ("Газель", 12.0, 15.0))
cursor.execute("INSERT OR IGNORE INTO cars (name, norm_highway, norm_city) VALUES (?, ?, ?)", ("УАЗ", 14.5, 18.0))

for admin_id in ADMIN_IDS:
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (admin_id,))
conn.commit()

# Обновляем баланс существующим пользователям, у которых меньше 500
cursor.execute("UPDATE drivers SET balance = 500 WHERE balance < 500")
conn.commit()

print("✅ База данных инициализирована")

# ========== ИНИЦИАЛИЗАЦИЯ VK ==========
try:
    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()
    
    groups = vk.groups.getById(group_id=VK_GROUP_ID)
    print(f"✅ Подключено к группе: {groups[0]['name']}")
    
    longpoll = VkBotLongPoll(vk_session, VK_GROUP_ID)
    print("✅ VK Бот запущен!")
    print("Нажмите Ctrl+C для остановки")
    
except Exception as e:
    print(f"❌ Ошибка: {e}")
    exit(1)

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("🚗 Выбрать авто", color=VkKeyboardColor.PRIMARY)
    keyboard.add_button("💰 Баланс", color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("➕ Поездка", color=VkKeyboardColor.POSITIVE)
    keyboard.add_button("⛽ Заправился", color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button("↩️ Отменить последнюю", color=VkKeyboardColor.SECONDARY)
    keyboard.add_button("✅ Закончить смену", color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_admin_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("📊 Статистика", color=VkKeyboardColor.PRIMARY)
    keyboard.add_button("📥 Выгрузить Excel", color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("➕ Добавить водителя", color=VkKeyboardColor.POSITIVE)
    keyboard.add_button("❌ Заблокировать водителя", color=VkKeyboardColor.NEGATIVE)
    keyboard.add_line()
    keyboard.add_button("💰 Пополнить баланс", color=VkKeyboardColor.POSITIVE)
    keyboard.add_button("🚗 Нормы расхода", color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("📢 Рассылка", color=VkKeyboardColor.PRIMARY)
    keyboard.add_button("📋 Список водителей", color=VkKeyboardColor.PRIMARY)
    return keyboard

def get_car_selection_keyboard():
    keyboard = VkKeyboard(one_time=True)
    cursor.execute("SELECT name FROM cars")
    cars = cursor.fetchall()
    for i, (car_name,) in enumerate(cars):
        if i % 2 == 0 and i > 0:
            keyboard.add_line()
        keyboard.add_button(car_name, color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("❌ Отмена", color=VkKeyboardColor.NEGATIVE)
    return keyboard

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def send_message(user_id, text, keyboard=None):
    """Отправка сообщения"""
    try:
        time.sleep(0.1)
        
        params = {
            'user_id': user_id,
            'random_id': get_random_id(),
            'message': text
        }
        
        if keyboard:
            params['keyboard'] = keyboard.get_keyboard()
        
        vk.messages.send(**params)
        return True
    except Exception as e:
        print(f"❌ Ошибка отправки пользователю {user_id}: {e}")
        return False

def get_balance(user_id):
    cursor.execute("SELECT balance FROM drivers WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else START_BALANCE

def update_balance(user_id, delta):
    cursor.execute("UPDATE drivers SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
    conn.commit()

def register_driver(user_id, username):
    cursor.execute("""
        INSERT OR IGNORE INTO drivers (user_id, username, balance, is_blocked, rate_per_shift, selected_car)
        VALUES (?, ?, ?, 0, 5, 'Газель')
    """, (user_id, username, START_BALANCE))
    conn.commit()

def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_driver_car(user_id):
    cursor.execute("SELECT selected_car FROM drivers WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else "Газель"

def set_driver_car(user_id, car_name):
    cursor.execute("UPDATE drivers SET selected_car = ? WHERE user_id = ?", (car_name, user_id))
    conn.commit()

def get_car_norms(car_name):
    cursor.execute("SELECT norm_highway, norm_city FROM cars WHERE name = ?", (car_name,))
    row = cursor.fetchone()
    return row if row else (12.0, 15.0)

def get_active_session(user_id):
    cursor.execute("SELECT id FROM sessions WHERE user_id = ? AND is_active = 1", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None

def get_session_summary(session_id):
    cursor.execute("""
        SELECT start_mileage, start_fuel, total_highway, total_city, total_refueled, car_name
        FROM sessions WHERE id = ?
    """, (session_id,))
    row = cursor.fetchone()
    if not row:
        return None
    start_mileage, start_fuel, total_hw, total_city, total_refueled, car_name = row
    total_km = total_hw + total_city
    norm_hw, norm_city = get_car_norms(car_name)
    fuel_used = (total_hw * norm_hw / 100) + (total_city * norm_city / 100)
    fuel_available = start_fuel + total_refueled
    return {
        "start_mileage": start_mileage,
        "total_hw": total_hw,
        "total_city": total_city,
        "total_km": total_km,
        "fuel_used": fuel_used,
        "fuel_available": fuel_available,
        "remaining": fuel_available - fuel_used,
        "start_fuel": start_fuel,
        "total_refueled": total_refueled,
        "car_name": car_name,
        "norm_hw": norm_hw,
        "norm_city": norm_city
    }

def show_stats(user_id, session_id):
    s = get_session_summary(session_id)
    if s:
        send_message(user_id,
            f"📊 Текущие итоги:\n"
            f"🚗 Авто: {s['car_name']} (трасса {s['norm_hw']:.2f} л/100км, город {s['norm_city']:.2f} л/100км)\n"
            f"Пробег: {s['total_km']:.2f} км (трасса {s['total_hw']:.2f}, город {s['total_city']:.2f})\n"
            f"Потрачено: {s['fuel_used']:.2f} л\n"
            f"Остаток в баке: {s['remaining']:.2f} л",
            get_main_keyboard()
        )

def show_balance(user_id):
    balance = get_balance(user_id)
    car = get_driver_car(user_id)
    norms = get_car_norms(car)
    
    message = (
        f"💰 Ваш баланс: {balance:.2f} руб\n"
        f"🚗 Текущий авто: {car}\n"
        f"📊 Нормы расхода: трасса {norms[0]:.2f} л/100км, город {norms[1]:.2f} л/100км\n"
        f"💸 Стоимость смены: {PRICE_PER_SHIFT} руб"
    )
    
    if balance < PRICE_PER_SHIFT:
        message += f"\n\n⚠️ Недостаточно средств для смены!"
        message += f"\nПополните баланс на {PRICE_PER_SHIFT - balance:.2f} руб"
    
    send_message(user_id, message, get_main_keyboard())

# ========== АДМИН ФУНКЦИИ ==========
def admin_stats(user_id):
    cursor.execute("SELECT COUNT(*) FROM drivers WHERE is_blocked = 0")
    active_drivers = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM sessions WHERE was_paid = 1")
    total_shifts = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(total_highway + total_city) FROM sessions WHERE was_paid = 1")
    total_km = cursor.fetchone()[0] or 0
    cursor.execute("SELECT SUM(balance) FROM drivers WHERE balance < 0")
    debt = cursor.fetchone()[0] or 0

    send_message(user_id,
        f"📊 СТАТИСТИКА\n\n"
        f"👥 Активных водителей: {active_drivers}\n"
        f"📋 Оплаченных смен: {total_shifts}\n"
        f"📏 Общий пробег: {total_km:.2f} км\n"
        f"💸 Задолженность: {abs(debt):.2f} руб",
        get_admin_keyboard()
    )

def admin_list_drivers(user_id):
    cursor.execute("SELECT user_id, username, balance, is_blocked, selected_car FROM drivers ORDER BY user_id")
    drivers = cursor.fetchall()
    if not drivers:
        send_message(user_id, "Нет зарегистрированных водителей")
        return
    
    text = "📋 Список водителей:\n\n"
    for driver_id, username, balance, is_blocked, car in drivers:
        status = "🔴 Заблокирован" if is_blocked else "🟢 Активен"
        name = username or str(driver_id)
        text += f"• {name} (ID: {driver_id})\n  🚗 {car} | Баланс: {balance:.2f} руб | {status}\n\n"
        if len(text) > 3000:
            send_message(user_id, text)
            text = ""
    
    send_message(user_id, text, get_admin_keyboard())

def admin_car_norms(user_id):
    cursor.execute("SELECT name, norm_highway, norm_city FROM cars")
    cars = cursor.fetchall()
    text = "🚗 Нормы расхода топлива:\n\n"
    for name, hw, city in cars:
        text += f"• {name}: трасса {hw:.2f} л/100км, город {city:.2f} л/100км\n"
    text += "\nДля изменения норм напишите:\n/set_norm Газель трасса 13.50 город 15.50"
    send_message(user_id, text, get_admin_keyboard())

# ========== ОБРАБОТЧИК СИГНАЛОВ ==========
bot_running = True

def signal_handler(sig, frame):
    global bot_running
    print(f'\n🛑 Получен сигнал остановки...')
    bot_running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Словарь для хранения состояний пользователей
user_data = {}

# ========== ОСНОВНОЙ ЦИКЛ ==========
print("🔄 Бот начал прослушивание сообщений...")
print(f"📝 PID процесса: {os.getpid()}")

try:
    while bot_running:
        try:
            events = longpoll.check()
            
            for event in events:
                if not bot_running:
                    break
                    
                if event.type == VkBotEventType.MESSAGE_NEW:
                    try:
                        # Игнорируем сообщения от бота и групп
                        if event.message.from_id < 0:
                            continue
                        
                        user_id = event.message.from_id
                        text = event.message.text.strip()
                        
                        # Получаем информацию о пользователе
                        try:
                            user_info = vk.users.get(user_ids=user_id)
                            username = user_info[0].get('first_name', str(user_id))
                        except:
                            username = str(user_id)
                        
                        register_driver(user_id, username)
                        
                        # Проверяем, заблокирован ли пользователь
                        cursor.execute("SELECT is_blocked FROM drivers WHERE user_id = ?", (user_id,))
                        result = cursor.fetchone()
                        if result and result[0] == 1 and not is_admin(user_id):
                            send_message(user_id, "⛔ Ваш аккаунт заблокирован. Обратитесь к администратору.")
                            continue
                        
                        # ===== АДМИН-КОМАНДЫ =====
                        if is_admin(user_id):
                            if text == "/admin":
                                send_message(user_id, "👨‍💼 Админ-панель", get_admin_keyboard())
                                continue
                                
                            elif text == "📊 Статистика":
                                admin_stats(user_id)
                                continue
                                
                            elif text == "📋 Список водителей":
                                admin_list_drivers(user_id)
                                continue
                                
                            elif text == "🚗 Нормы расхода":
                                admin_car_norms(user_id)
                                continue
                                
                            elif text == "💰 Пополнить баланс":
                                send_message(user_id, "💰 Введите ID пользователя и сумму:\nФормат: /topup ID СУММА\nПример: /topup 75074039 100")
                                continue
                                
                            elif text.startswith("/topup"):
                                try:
                                    parts = text.split()
                                    if len(parts) != 3:
                                        send_message(user_id, "❌ Формат: /topup ID СУММА")
                                        continue
                                    target_user = int(parts[1])
                                    amount = float(parts[2])
                                    
                                    cursor.execute("SELECT user_id FROM drivers WHERE user_id = ?", (target_user,))
                                    if not cursor.fetchone():
                                        register_driver(target_user, str(target_user))
                                        cursor.execute("UPDATE drivers SET balance = balance + ? WHERE user_id = ?", (amount, target_user))
                                    else:
                                        cursor.execute("UPDATE drivers SET balance = balance + ? WHERE user_id = ?", (amount, target_user))
                                    
                                    cursor.execute("INSERT INTO payments (user_id, amount, admin_id) VALUES (?, ?, ?)", (target_user, amount, user_id))
                                    conn.commit()
                                    
                                    new_balance = get_balance(target_user)
                                    send_message(user_id, f"✅ Баланс пополнен на {amount:.2f} руб\n💰 Новый баланс: {new_balance:.2f} руб")
                                    
                                    try:
                                        send_message(target_user, f"💰 Ваш баланс пополнен на {amount:.2f} руб\nТекущий баланс: {new_balance:.2f} руб")
                                    except:
                                        pass
                                except Exception as e:
                                    send_message(user_id, f"❌ Ошибка: {e}")
                                continue
                                
                            elif text == "📢 Рассылка":
                                send_message(user_id, "📢 Введите сообщение для рассылки (для отмены напишите 'отмена'):")
                                user_data[user_id] = {'state': 'admin_broadcast'}
                                continue
                                
                            elif text == "➕ Добавить водителя":
                                send_message(user_id, "Введите ID пользователя для добавления:")
                                user_data[user_id] = {'state': 'admin_add_driver'}
                                continue
                                
                            elif text == "❌ Заблокировать водителя":
                                send_message(user_id, "Введите ID пользователя для блокировки:")
                                user_data[user_id] = {'state': 'admin_block_driver'}
                                continue
                                
                            elif text == "📥 Выгрузить Excel":
                                send_message(user_id, "📥 Функция выгрузки Excel в разработке")
                                continue
                                
                            elif text.startswith("/set_norm"):
                                try:
                                    parts = text.split()
                                    if len(parts) >= 6 and parts[2] == "трасса" and parts[4] == "город":
                                        car_name = parts[1]
                                        hw_norm = float(parts[3])
                                        city_norm = float(parts[5])
                                        
                                        cursor.execute("""
                                            UPDATE cars SET norm_highway = ?, norm_city = ? 
                                            WHERE name = ?
                                        """, (hw_norm, city_norm, car_name))
                                        conn.commit()
                                        
                                        if cursor.rowcount > 0:
                                            send_message(user_id, f"✅ Нормы для {car_name} обновлены:\nТрасса: {hw_norm:.2f} л/100км\nГород: {city_norm:.2f} л/100км")
                                        else:
                                            send_message(user_id, f"❌ Автомобиль '{car_name}' не найден")
                                    else:
                                        send_message(user_id, "❌ Неверный формат. Используйте: /set_norm Газель трасса 12.5 город 15.5")
                                except Exception as e:
                                    send_message(user_id, f"❌ Ошибка: {e}")
                                continue
                        
                        # ===== ОБРАБОТКА СОСТОЯНИЙ ПОЛЬЗОВАТЕЛЯ =====
                        if user_id in user_data:
                            state = user_data[user_id].get('state')
                            
                            if state == 'admin_broadcast':
                                if text.lower() == 'отмена':
                                    del user_data[user_id]
                                    send_message(user_id, "❌ Рассылка отменена", get_admin_keyboard())
                                    continue
                                
                                cursor.execute("SELECT user_id FROM drivers WHERE is_blocked = 0")
                                drivers = cursor.fetchall()
                                success = 0
                                fail = 0
                                for (driver_id,) in drivers:
                                    try:
                                        send_message(driver_id, f"📢 Сообщение от администрации:\n\n{text}")
                                        success += 1
                                    except:
                                        fail += 1
                                    time.sleep(0.1)
                                send_message(user_id, f"✅ Рассылка завершена\nОтправлено: {success}\nНе доставлено: {fail}", get_admin_keyboard())
                                del user_data[user_id]
                                continue
                                
                            elif state == 'admin_add_driver':
                                if text.lower() == 'отмена':
                                    del user_data[user_id]
                                    send_message(user_id, "❌ Отменено", get_admin_keyboard())
                                    continue
                                
                                try:
                                    new_user_id = int(text)
                                    register_driver(new_user_id, str(new_user_id))
                                    send_message(user_id, f"✅ Водитель {new_user_id} добавлен с балансом {START_BALANCE} руб", get_admin_keyboard())
                                except:
                                    send_message(user_id, "❌ Ошибка! Введите числовой ID")
                                del user_data[user_id]
                                continue
                                
                            elif state == 'admin_block_driver':
                                if text.lower() == 'отмена':
                                    del user_data[user_id]
                                    send_message(user_id, "❌ Отменено", get_admin_keyboard())
                                    continue
                                
                                try:
                                    block_user_id = int(text)
                                    cursor.execute("UPDATE drivers SET is_blocked = 1 WHERE user_id = ?", (block_user_id,))
                                    conn.commit()
                                    if cursor.rowcount > 0:
                                        send_message(user_id, f"✅ Водитель {block_user_id} заблокирован", get_admin_keyboard())
                                    else:
                                        send_message(user_id, f"❌ Водитель {block_user_id} не найден", get_admin_keyboard())
                                except:
                                    send_message(user_id, "❌ Ошибка! Введите числовой ID")
                                del user_data[user_id]
                                continue
                                
                            elif state == 'waiting_mileage':
                                if text.lower() == 'отмена':
                                    del user_data[user_id]
                                    send_message(user_id, "❌ Начало смены отменено", get_main_keyboard())
                                    continue
                                
                                try:
                                    mileage = float(text.replace(',', '.'))
                                    if mileage < 0:
                                        send_message(user_id, "❌ Пробег не может быть отрицательным!")
                                        continue
                                    
                                    # Проверяем баланс
                                    balance = get_balance(user_id)
                                    if balance < PRICE_PER_SHIFT:
                                        del user_data[user_id]
                                        send_message(user_id, 
                                            f"❌ Недостаточно средств для начала смены!\n"
                                            f"💰 Баланс: {balance:.2f} руб\n"
                                            f"💸 Стоимость смены: {PRICE_PER_SHIFT} руб\n"
                                            f"📉 Не хватает: {PRICE_PER_SHIFT - balance:.2f} руб",
                                            get_main_keyboard()
                                        )
                                        continue
                                    
                                    user_data[user_id]['start_mileage'] = mileage
                                    user_data[user_id]['state'] = 'waiting_fuel'
                                    send_message(user_id, "⛽ Введите количество топлива в баке (литры):")
                                except:
                                    send_message(user_id, "❌ Введите число!")
                                continue
                                
                            elif state == 'waiting_fuel':
                                if text.lower() == 'отмена':
                                    del user_data[user_id]
                                    send_message(user_id, "❌ Начало смены отменено", get_main_keyboard())
                                    continue
                                
                                try:
                                    fuel = float(text.replace(',', '.'))
                                    if fuel < 0:
                                        send_message(user_id, "❌ Количество топлива не может быть отрицательным!")
                                        continue
                                    
                                    car_name = get_driver_car(user_id)
                                    start_mileage = user_data[user_id]['start_mileage']
                                    
                                    cursor.execute("UPDATE sessions SET is_active = 0, ended_at = CURRENT_TIMESTAMP WHERE user_id = ? AND is_active = 1", (user_id,))
                                    
                                    cursor.execute("""
                                        INSERT INTO sessions (user_id, car_name, start_mileage, start_fuel, is_active)
                                        VALUES (?, ?, ?, ?, 1)
                                    """, (user_id, car_name, start_mileage, fuel))
                                    conn.commit()
                                    session_id = cursor.lastrowid
                                    
                                    del user_data[user_id]
                                    send_message(user_id, f"✅ Смена начата. Автомобиль: {car_name}", get_main_keyboard())
                                    show_stats(user_id, session_id)
                                except:
                                    send_message(user_id, "❌ Введите число!")
                                continue
                                
                            elif state == 'waiting_highway':
                                if text.lower() == 'отмена':
                                    del user_data[user_id]
                                    send_message(user_id, "❌ Добавление поездки отменено", get_main_keyboard())
                                    continue
                                
                                try:
                                    highway = float(text.replace(',', '.'))
                                    if highway < 0:
                                        send_message(user_id, "❌ Километраж не может быть отрицательным!")
                                        continue
                                    user_data[user_id]['highway'] = highway
                                    user_data[user_id]['state'] = 'waiting_city'
                                    send_message(user_id, "🏙 Введите километраж по городу:")
                                except:
                                    send_message(user_id, "❌ Введите число!")
                                continue
                                
                            elif state == 'waiting_city':
                                if text.lower() == 'отмена':
                                    del user_data[user_id]
                                    send_message(user_id, "❌ Добавление поездки отменено", get_main_keyboard())
                                    continue
                                
                                try:
                                    city = float(text.replace(',', '.'))
                                    if city < 0:
                                        send_message(user_id, "❌ Километраж не может быть отрицательным!")
                                        continue
                                    
                                    session_id = user_data[user_id]['session_id']
                                    highway = user_data[user_id]['highway']
                                    
                                    cursor.execute("INSERT INTO trips (session_id, highway, city) VALUES (?, ?, ?)", (session_id, highway, city))
                                    cursor.execute("UPDATE sessions SET total_highway = total_highway + ?, total_city = total_city + ? WHERE id = ?", (highway, city, session_id))
                                    conn.commit()
                                    
                                    del user_data[user_id]
                                    send_message(user_id, f"✅ Добавлено: трасса {highway:.2f} км, город {city:.2f} км")
                                    show_stats(user_id, session_id)
                                except:
                                    send_message(user_id, "❌ Ошибка!")
                                continue
                                
                            elif state == 'waiting_refuel':
                                if text.lower() == 'отмена':
                                    del user_data[user_id]
                                    send_message(user_id, "❌ Заправка отменена", get_main_keyboard())
                                    continue
                                
                                try:
                                    liters = float(text.replace(',', '.'))
                                    if liters <= 0:
                                        send_message(user_id, "❌ Количество топлива должно быть положительным!")
                                        continue
                                    
                                    session_id = user_data[user_id]['session_id']
                                    
                                    cursor.execute("UPDATE sessions SET total_refueled = total_refueled + ? WHERE id = ?", (liters, session_id))
                                    conn.commit()
                                    
                                    del user_data[user_id]
                                    send_message(user_id, f"✅ Заправлено {liters:.2f} л")
                                    show_stats(user_id, session_id)
                                except:
                                    send_message(user_id, "❌ Введите число!")
                                continue
                                
                            elif state == 'selecting_car':
                                if text == "❌ Отмена":
                                    del user_data[user_id]
                                    send_message(user_id, "❌ Выбор отменен", get_main_keyboard())
                                    continue
                                
                                cursor.execute("SELECT name FROM cars WHERE name = ?", (text,))
                                car = cursor.fetchone()
                                if car:
                                    car_name = car[0]
                                    set_driver_car(user_id, car_name)
                                    norms = get_car_norms(car_name)
                                    del user_data[user_id]
                                    send_message(user_id, 
                                        f"✅ Выбран автомобиль: {car_name}\n"
                                        f"Нормы расхода: трасса {norms[0]:.2f} л/100км, город {norms[1]:.2f} л/100км",
                                        get_main_keyboard()
                                    )
                                else:
                                    send_message(user_id, "❌ Такого автомобиля нет в списке. Выберите из предложенных вариантов или нажмите 'Отмена'", get_car_selection_keyboard())
                                continue
                        
                        # ===== ОБЫЧНЫЕ КОМАНДЫ =====
                        elif text == "🚗 Выбрать авто":
                            send_message(user_id, "🚗 Выберите автомобиль:", get_car_selection_keyboard())
                            user_data[user_id] = {'state': 'selecting_car'}
                            continue
                            
                        elif text == "💰 Баланс":
                            show_balance(user_id)
                            continue
                            
                        elif text == "➕ Поездка":
                            session_id = get_active_session(user_id)
                            if not session_id:
                                # Проверяем баланс перед началом смены
                                balance = get_balance(user_id)
                                if balance < PRICE_PER_SHIFT:
                                    send_message(user_id, 
                                        f"❌ Недостаточно средств для начала смены!\n\n"
                                        f"💰 Ваш баланс: {balance:.2f} руб\n"
                                        f"💸 Стоимость смены: {PRICE_PER_SHIFT} руб\n"
                                        f"📉 Не хватает: {PRICE_PER_SHIFT - balance:.2f} руб\n\n"
                                        f"Пополните баланс через администратора.",
                                        get_main_keyboard()
                                    )
                                    continue
                                
                                send_message(user_id, "🚚 Для начала введите начальный пробег (км):")
                                user_data[user_id] = {'state': 'waiting_mileage'}
                            else:
                                send_message(user_id, "🛣 Введите километраж по трассе:")
                                user_data[user_id] = {'state': 'waiting_highway', 'session_id': session_id}
                            continue
                            
                        elif text == "⛽ Заправился":
                            session_id = get_active_session(user_id)
                            if not session_id:
                                send_message(user_id, "❌ Нет активной смены. Начните новую смену (кнопка '➕ Поездка')")
                            else:
                                send_message(user_id, "⛽ Введите количество заправленного топлива (литры):")
                                user_data[user_id] = {'state': 'waiting_refuel', 'session_id': session_id}
                            continue
                            
                        elif text == "↩️ Отменить последнюю":
                            session_id = get_active_session(user_id)
                            if not session_id:
                                send_message(user_id, "❌ Нет активной смены")
                            else:
                                cursor.execute("SELECT id FROM trips WHERE session_id = ? ORDER BY id DESC LIMIT 1", (session_id,))
                                trip = cursor.fetchone()
                                if trip:
                                    trip_id = trip[0]
                                    cursor.execute("SELECT highway, city FROM trips WHERE id = ?", (trip_id,))
                                    hw, city = cursor.fetchone()
                                    cursor.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
                                    cursor.execute("UPDATE sessions SET total_highway = total_highway - ?, total_city = total_city - ? WHERE id = ?", (hw, city, session_id))
                                    conn.commit()
                                    send_message(user_id, f"✅ Последняя поездка отменена (трасса {hw:.2f} км, город {city:.2f} км)")
                                    show_stats(user_id, session_id)
                                else:
                                    send_message(user_id, "❌ Нет поездок для отмены")
                            continue
                            
                        elif text == "✅ Закончить смену":
                            session_id = get_active_session(user_id)
                            if not session_id:
                                send_message(user_id, "❌ Нет активной смены")
                            else:
                                s = get_session_summary(session_id)
                                if s:
                                    balance_before = get_balance(user_id)
                                    
                                    # Проверяем, хватает ли денег
                                    if balance_before < PRICE_PER_SHIFT:
                                        send_message(user_id, 
                                            f"❌ Недостаточно средств для оплаты смены!\n\n"
                                            f"💰 Ваш баланс: {balance_before:.2f} руб\n"
                                            f"💸 Стоимость смены: {PRICE_PER_SHIFT} руб\n"
                                            f"📉 Не хватает: {PRICE_PER_SHIFT - balance_before:.2f} руб\n\n"
                                            f"Пополните баланс для завершения смены.",
                                            get_main_keyboard()
                                        )
                                        continue
                                    
                                    # Списываем деньги
                                    update_balance(user_id, -PRICE_PER_SHIFT)
                                    balance_after = get_balance(user_id)
                                    
                                    cursor.execute("UPDATE sessions SET is_active = 0, was_paid = 1, ended_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,))
                                    conn.commit()
                                    
                                    message = (
                                        f"✅ Смена завершена!\n\n"
                                        f"📊 ИТОГИ СМЕНЫ:\n"
                                        f"🚗 Авто: {s['car_name']}\n"
                                        f"🛣 Общий пробег: {s['total_km']:.2f} км\n"
                                        f"   - Трасса: {s['total_hw']:.2f} км\n"
                                        f"   - Город: {s['total_city']:.2f} км\n"
                                        f"⛽ Начало смены: {s['start_fuel']:.2f} л\n"
                                        f"⛽ Заправлено: {s['total_refueled']:.2f} л\n"
                                        f"📉 Расход по норме: {s['fuel_used']:.2f} л\n"
                                        f"💧 Остаток: {s['remaining']:.2f} л\n\n"
                                        f"💰 Списано за смену: {PRICE_PER_SHIFT} руб\n"
                                        f"💰 Баланс: {balance_before:.2f} → {balance_after:.2f} руб"
                                    )
                                    send_message(user_id, message, get_main_keyboard())
                                else:
                                    send_message(user_id, "❌ Ошибка при завершении смены")
                            continue
                            
                        else:
                            if not is_admin(user_id):
                                send_message(user_id, "Используйте кнопки меню для работы с ботом", get_main_keyboard())
                            else:
                                send_message(user_id, "Используйте кнопки меню или команду /admin", get_admin_keyboard())
                    
                    except Exception as e:
                        print(f"❌ Ошибка обработки сообщения: {e}")
        
        except Exception as e:
            if not bot_running:
                break
            print(f"⚠️ Ошибка в цикле: {e}")
            time.sleep(1)
            continue

except KeyboardInterrupt:
    print("\n🛑 Получен KeyboardInterrupt")
except Exception as e:
    print(f"❌ Критическая ошибка: {e}")
finally:
    print("🔒 Закрываем соединение с БД...")
    conn.close()
    lock_fp.close()
    print("✅ Бот корректно остановлен")
    sys.exit(0)