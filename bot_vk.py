import sqlite3
import time
from datetime import datetime
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id

# ========== НАСТРОЙКИ ==========
VK_TOKEN = "vk1.a.iKPy742qB3R9M6tWvmRgk0BuyR2JO36Lp4UZkM0pVH-KmBbL5OLQoYgxTjommXbfDtsfHEIh6tWltbqydzkiefVFD-jy8QYSO6Y1Si7VpjhDziFcHEHRazAA1hsLg8ACIpQyzdIPlNouWhPEYQZbeV4_CBagFwGAZ5MprVRBmfowvHb9Ma8_MgvgeacK42IbO8c4uyJhXA2QirX-cGrG5A"
VK_GROUP_ID = 240344015
ADMIN_IDS = [1121983645]
PRICE_PER_SHIFT = 5

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
    balance REAL DEFAULT 0,
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

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def send_message(user_id, text, keyboard=None):
    try:
        vk.messages.send(
            user_id=user_id,
            random_id=get_random_id(),
            message=text,
            keyboard=keyboard.get_keyboard() if keyboard else None
        )
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def get_balance(user_id):
    cursor.execute("SELECT balance FROM drivers WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0.0

def update_balance(user_id, delta):
    cursor.execute("UPDATE drivers SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
    conn.commit()

def register_driver(user_id, username):
    cursor.execute("""
        INSERT OR IGNORE INTO drivers (user_id, username, balance, is_blocked, rate_per_shift, selected_car)
        VALUES (?, ?, 500, 0, 5, 'Газель')
    """, (user_id, username))
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
    send_message(user_id,
        f"💰 Ваш баланс: {balance:.2f} руб\n"
        f"🚗 Текущий авто: {car}\n"
        f"📊 Нормы расхода: трасса {norms[0]:.2f} л/100км, город {norms[1]:.2f} л/100км\n"
        f"💸 Стоимость смены: {PRICE_PER_SHIFT} руб",
        get_main_keyboard()
    )

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
    if text:
        send_message(user_id, text, get_admin_keyboard())

def admin_car_norms(user_id):
    cursor.execute("SELECT name, norm_highway, norm_city FROM cars")
    cars = cursor.fetchall()
    text = "🚗 Нормы расхода топлива:\n\n"
    for name, hw, city in cars:
        text += f"• {name}: трасса {hw:.2f} л/100км, город {city:.2f} л/100км\n"
    text += "\nДля изменения норм напишите:\n`/set_norm Газель трасса 13.50`"
    send_message(user_id, text, get_admin_keyboard())

user_data = {}

# ========== ОСНОВНОЙ ЦИКЛ ==========
for event in longpoll.listen():
    if event.type == VkBotEventType.MESSAGE_NEW:
        try:
            user_id = event.message.from_id
            text = event.message.text
            
            user_info = vk.users.get(user_ids=user_id)
            username = user_info[0].get('first_name', str(user_id))
            register_driver(user_id, username)
            
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
                        
                        cursor.execute("UPDATE drivers SET balance = balance + ? WHERE user_id = ?", (amount, target_user))
                        conn.commit()
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
                    send_message(user_id, "📢 Введите сообщение для рассылки:")
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
            
            # ===== ОБРАБОТКА СОСТОЯНИЙ =====
            if user_id in user_data:
                state = user_data[user_id].get('state')
                
                if state == 'admin_broadcast':
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
                        time.sleep(0.05)
                    send_message(user_id, f"✅ Рассылка завершена\nОтправлено: {success}\nНе доставлено: {fail}")
                    del user_data[user_id]
                    continue
                    
                elif state == 'admin_add_driver':
                    try:
                        new_user_id = int(text)
                        register_driver(new_user_id, str(new_user_id))
                        send_message(user_id, f"✅ Водитель {new_user_id} добавлен")
                    except:
                        send_message(user_id, "❌ Ошибка! Введите числовой ID")
                    del user_data[user_id]
                    continue
                    
                elif state == 'admin_block_driver':
                    try:
                        block_user_id = int(text)
                        cursor.execute("UPDATE drivers SET is_blocked = 1 WHERE user_id = ?", (block_user_id,))
                        conn.commit()
                        send_message(user_id, f"✅ Водитель {block_user_id} заблокирован")
                    except:
                        send_message(user_id, "❌ Ошибка!")
                    del user_data[user_id]
                    continue
                    
                elif state == 'waiting_mileage':
                    try:
                        mileage = float(text.replace(',', '.'))
                        user_data[user_id]['start_mileage'] = mileage
                        user_data[user_id]['state'] = 'waiting_fuel'
                        send_message(user_id, "⛽ Введите количество топлива в баке (литры):")
                    except:
                        send_message(user_id, "❌ Введите число!")
                    continue
                    
                elif state == 'waiting_fuel':
                    try:
                        fuel = float(text.replace(',', '.'))
                        car_name = get_driver_car(user_id)
                        start_mileage = user_data[user_id]['start_mileage']
                        
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
                    try:
                        highway = float(text.replace(',', '.'))
                        user_data[user_id]['highway'] = highway
                        user_data[user_id]['state'] = 'waiting_city'
                        send_message(user_id, "🏙 Введите километраж по городу:")
                    except:
                        send_message(user_id, "❌ Введите число!")
                    continue
                    
                elif state == 'waiting_city':
                    try:
                        city = float(text.replace(',', '.'))
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
                    try:
                        liters = float(text.replace(',', '.'))
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
                    
                    try:
                        car_name = text
                        cursor.execute("SELECT name, norm_highway, norm_city FROM cars WHERE name = ?", (car_name,))
                        car = cursor.fetchone()
                        
                        if car:
                            set_driver_car(user_id, car_name)
                            send_message(
                                user_id, 
                                f"✅ Выбран автомобиль: {car_name}\n"
                                f"📊 Нормы расхода: трасса {car[1]:.2f} л/100км, город {car[2]:.2f} л/100км",
                                get_main_keyboard()
                            )
                        else:
                            send_message(user_id, "❌ Автомобиль не найден. Выберите из списка.")
                        
                        del user_data[user_id]
                    except Exception as e:
                        print(f"Ошибка: {e}")
                        send_message(user_id, "⚠️ Ошибка при выборе автомобиля")
                        del user_data[user_id]
                    continue
            
            # ===== ОСНОВНЫЕ КОМАНДЫ =====
            if text.lower() == "/start":
                if get_active_session(user_id):
                    send_message(user_id, "У вас уже есть активная смена!", get_main_keyboard())
                    session_id = get_active_session(user_id)
                    show_stats(user_id, session_id)
                    continue
                
                balance = get_balance(user_id)
                if balance < PRICE_PER_SHIFT:
                    send_message(user_id, f"⚠️ Недостаточно средств. Баланс: {balance:.2f} руб\nСтоимость смены: {PRICE_PER_SHIFT} руб", get_main_keyboard())
                    continue
                
                send_message(user_id, "🚛 Начало смены.\nВведите пробег на одометре (км):")
                user_data[user_id] = {'state': 'waiting_mileage'}
                continue
                
            elif text == "💰 Баланс" or text.lower() == "/balance":
                show_balance(user_id)
                continue
                
            elif text == "🚗 Выбрать авто":
                cursor.execute("SELECT name FROM cars")
                cars = cursor.fetchall()
                
                if not cars:
                    send_message(user_id, "❌ Нет доступных автомобилей")
                    continue
                
                keyboard = VkKeyboard(one_time=False)
                for car in cars:
                    keyboard.add_button(car[0], color=VkKeyboardColor.PRIMARY)
                    keyboard.add_line()
                keyboard.add_button("❌ Отмена", color=VkKeyboardColor.NEGATIVE)
                
                current_car = get_driver_car(user_id)
                send_message(
                    user_id, 
                    f"🚗 Выберите автомобиль:\nТекущий: {current_car}",
                    keyboard
                )
                user_data[user_id] = {'state': 'selecting_car'}
                continue
                
            elif text == "➕ Поездка":
                session_id = get_active_session(user_id)
                if not session_id:
                    send_message(user_id, "❌ Нет активной смены. Напишите /start")
                    continue
                user_data[user_id] = {'state': 'waiting_highway', 'session_id': session_id}
                send_message(user_id, "🛣 Сколько километров по ТРАССЕ? (число)")
                continue
                
            elif text == "⛽ Заправился":
                session_id = get_active_session(user_id)
                if not session_id:
                    send_message(user_id, "❌ Нет активной смены. Напишите /start")
                    continue
                user_data[user_id] = {'state': 'waiting_refuel', 'session_id': session_id}
                send_message(user_id, "⛽ Сколько литров заправили?")
                continue
                
            elif text == "↩️ Отменить последнюю":
                session_id = get_active_session(user_id)
                if not session_id:
                    send_message(user_id, "❌ Нет активной смены")
                    continue
                cursor.execute("SELECT id, highway, city FROM trips WHERE session_id = ? ORDER BY created_at DESC LIMIT 1", (session_id,))
                last = cursor.fetchone()
                if not last:
                    send_message(user_id, "❌ Нет поездок для отмены")
                    continue
                trip_id, highway, city = last
                cursor.execute("UPDATE sessions SET total_highway = total_highway - ?, total_city = total_city - ? WHERE id = ?", (highway, city, session_id))
                cursor.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
                conn.commit()
                send_message(user_id, f"❌ Отменена последняя поездка (трасса {highway:.2f} км, город {city:.2f} км)")
                show_stats(user_id, session_id)
                continue
                
            elif text == "✅ Закончить смену":
                session_id = get_active_session(user_id)
                if not session_id:
                    send_message(user_id, "❌ Нет активной смены")
                    continue
                
                s = get_session_summary(session_id)
                if not s:
                    continue
                
                balance = get_balance(user_id)
                if balance < PRICE_PER_SHIFT:
                    send_message(user_id, f"❌ Недостаточно средств. Баланс: {balance:.2f} руб\nСтоимость смены: {PRICE_PER_SHIFT} руб")
                    cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                    cursor.execute("DELETE FROM trips WHERE session_id = ?", (session_id,))
                    conn.commit()
                    continue
                
                end_mileage = s["start_mileage"] + s["total_km"]
                update_balance(user_id, -PRICE_PER_SHIFT)
                cursor.execute("UPDATE sessions SET is_active = 0, was_paid = 1, ended_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,))
                conn.commit()
                
                new_balance = get_balance(user_id)
                report = f"""
📊 ОТЧЁТ ЗА СМЕНУ

🚗 Автомобиль: {s['car_name']}
📊 Нормы расхода: трасса {s['norm_hw']:.2f} л/100км, город {s['norm_city']:.2f} л/100км

📌 Километраж:
- По трассе: {s['total_hw']:.2f} км
- По городу: {s['total_city']:.2f} км
- Всего: {s['total_km']:.2f} км
- Пробег: {s['start_mileage']:.0f} → {end_mileage:.0f}

⛽ Расход топлива (по норме):
- Итого потрачено: {s['fuel_used']:.2f} л

📥 Было топлива:
- На начало: {s['start_fuel']:.2f} л
- Заправлено: {s['total_refueled']:.2f} л

📤 Остаток в баке: {s['remaining']:.2f} л

💰 Оплата:
- Списано: {PRICE_PER_SHIFT} руб
- Остаток: {new_balance:.2f} руб

✅ Смена завершена. Для новой смены нажмите /start
"""
                send_message(user_id, report, get_main_keyboard())
                continue
                
            else:
                send_message(user_id, "❓ Неизвестная команда\n/start - начать смену\n/balance - баланс\n/help - помощь", get_main_keyboard())
                
        except Exception as e:
            print(f"Ошибка: {e}")
            try:
                send_message(user_id, "⚠️ Произошла ошибка. Попробуйте еще раз.")
            except:
                pass