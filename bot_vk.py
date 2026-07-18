import sqlite3
import threading
import time
from datetime import datetime
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id
import openpyxl
from io import BytesIO
import re

# ========== НАСТРОЙКИ ==========
VK_TOKEN = "vk1.a.iKPy742qB3R9M6tWvmRgk0BuyR2JO36Lp4UZkM0pVH-KmBbL5OLQoYgxTjommXbfDtsfHEIh6tWltbqydzkiefVFD-jy8QYSO6Y1Si7VpjhDziFcHEHRazAA1hsLg8ACIpQyzdIPlNouWhPEYQZbeV4_CBagFwGAZ5MprVRBmfowvHb9Ma8_MgvgeacK42IbO8c4uyJhXA2QirX-cGrG5A"  # Токен группы ВК
VK_GROUP_ID = 240344015  # ID вашей группы
PRICE_PER_SHIFT = 5
ADMIN_IDS = [75074039]  # ID пользователей ВК (числовые)

# ========== БАЗА ДАННЫХ ==========
conn = sqlite3.connect("waybills.db", check_same_thread=False)
cursor = conn.cursor()

# ... (все CREATE TABLE запросы остаются без изменений) ...

# ========== ИНИЦИАЛИЗАЦИЯ VK ==========
vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()
longpoll = VkBotLongPoll(vk_session, VK_GROUP_ID)

# ========== КЛАВИАТУРЫ ДЛЯ VK ==========
def get_main_keyboard():
    keyboard = VkKeyboard(one_time=False, inline=False)
    keyboard.add_button("🚗 Выбрать авто", color=VkKeyboardColor.PRIMARY)
    keyboard.add_button("💰 Баланс", color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("➕ Поездка", color=VkKeyboardColor.POSITIVE)
    keyboard.add_button("⛽ Заправился", color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button("✅ Закончить смену", color=VkKeyboardColor.NEGATIVE)
    return keyboard

def get_keyboard_with_undo():
    keyboard = VkKeyboard(one_time=False, inline=False)
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
    keyboard = VkKeyboard(one_time=False, inline=False)
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
def send_message(user_id, text, keyboard=None, attachment=None):
    """Отправка сообщения пользователю VK"""
    try:
        vk.messages.send(
            user_id=user_id,
            random_id=get_random_id(),
            message=text,
            keyboard=keyboard.get_keyboard() if keyboard else None,
            attachment=attachment
        )
    except Exception as e:
        print(f"Ошибка отправки сообщения {user_id}: {e}")

def get_user_name(user_id):
    """Получить имя пользователя по ID"""
    try:
        user = vk.users.get(user_ids=user_id, fields='first_name,last_name')[0]
        return f"{user['first_name']} {user['last_name']}"
    except:
        return str(user_id)

# ========== ФУНКЦИИ БАЗЫ ДАННЫХ (без изменений) ==========
def is_admin(user_id):
    cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None

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
        VALUES (?, ?, 0, 0, 5, 'Газель')
    """, (user_id, username))
    conn.commit()

def is_driver_blocked(user_id):
    cursor.execute("SELECT is_blocked FROM drivers WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] == 1 if row else False

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

# ========== ОБРАБОТЧИКИ СООБЩЕНИЙ ==========

class VKBot:
    def __init__(self):
        self.user_data = {}
        
    def show_stats(self, user_id, session_id):
        s = get_session_summary(session_id)
        if s:
            send_message(user_id,
                f"📊 Текущие итоги:\n"
                f"🚗 Авто: {s['car_name']} (трасса {s['norm_hw']:.2f} л/100км, город {s['norm_city']:.2f} л/100км)\n"
                f"Пробег: {s['total_km']:.2f} км (трасса {s['total_hw']:.2f}, город {s['total_city']:.2f})\n"
                f"Потрачено: {s['fuel_used']:.2f} л\n"
                f"Остаток в баке: {s['remaining']:.2f} л",
                get_keyboard_with_undo()
            )

    def show_balance(self, user_id):
        balance = get_balance(user_id)
        car = get_driver_car(user_id)
        norms = get_car_norms(car)
        send_message(user_id,
            f"💰 Ваш баланс: {balance:.2f} руб\n"
            f"🚗 Текущий авто: {car}\n"
            f"📊 Нормы расхода: трасса {norms[0]:.2f} л/100км, город {norms[1]:.2f} л/100км\n"
            f"💸 Стоимость смены: {PRICE_PER_SHIFT} руб")

    def handle_start(self, user_id):
        username = get_user_name(user_id)
        register_driver(user_id, username)

        if is_driver_blocked(user_id):
            send_message(user_id, "❌ Ваш аккаунт заблокирован. Обратитесь к администратору.")
            return

        balance = get_balance(user_id)
        if balance < PRICE_PER_SHIFT:
            send_message(user_id,
                f"⚠️ Недостаточно средств для начала смены.\n"
                f"Ваш баланс: {balance:.2f} руб\n"
                f"Стоимость смены: {PRICE_PER_SHIFT} руб\n\n"
                f"Пополните баланс через администратора.",
                get_main_keyboard())
            return

        if get_active_session(user_id):
            send_message(user_id, "У вас уже есть активная смена!", get_keyboard_with_undo())
            return

        send_message(user_id, "🚛 Начало смены.\nВведите пробег на одометре (км):")
        self.user_data[user_id] = {'state': 'waiting_mileage'}

    def handle_mileage(self, user_id, text):
        try:
            mileage = float(text)
            self.user_data[user_id] = {'state': 'waiting_fuel', 'start_mileage': mileage}
            send_message(user_id, "⛽ Введите количество топлива в баке (литры):")
        except:
            send_message(user_id, "❌ Введите число!")

    def handle_fuel(self, user_id, text):
        try:
            fuel = float(text)
            data = self.user_data[user_id]
            car_name = get_driver_car(user_id)

            cursor.execute("""
                INSERT INTO sessions (user_id, car_name, start_mileage, start_fuel, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (user_id, car_name, data['start_mileage'], fuel))
            conn.commit()
            session_id = cursor.lastrowid

            del self.user_data[user_id]
            send_message(user_id, f"✅ Смена начата. Автомобиль: {car_name}", get_keyboard_with_undo())
            self.show_stats(user_id, session_id)
        except:
            send_message(user_id, "❌ Введите число!")

    def handle_select_car(self, user_id):
        cursor.execute("SELECT name FROM cars")
        cars = cursor.fetchall()
        
        keyboard = VkKeyboard(one_time=False, inline=True)
        for car in cars:
            keyboard.add_button(car[0], color=VkKeyboardColor.PRIMARY, payload={"car": car[0]})
            keyboard.add_line()

        current_car = get_driver_car(user_id)
        send_message(user_id, f"🚗 Выберите автомобиль:\nТекущий: {current_car}", keyboard)

    def handle_car_selection(self, user_id, car_name):
        set_driver_car(user_id, car_name)
        norms = get_car_norms(car_name)
        send_message(user_id,
            f"✅ Выбран автомобиль: {car_name}\n"
            f"📊 Нормы расхода: трасса {norms[0]:.2f} л/100км, город {norms[1]:.2f} л/100км",
            get_keyboard_with_undo()
        )

    def handle_add_trip(self, user_id):
        if is_driver_blocked(user_id):
            send_message(user_id, "❌ Ваш аккаунт заблокирован")
            return

        session_id = get_active_session(user_id)
        if not session_id:
            send_message(user_id, "❌ Нет активной смены. Напишите /start")
            return

        self.user_data[user_id] = {'state': 'waiting_highway', 'session_id': session_id}
        send_message(user_id, "🛣 Сколько километров по ТРАССЕ? (число)")

    def handle_highway(self, user_id, text):
        try:
            highway = float(text)
            self.user_data[user_id]['highway'] = highway
            self.user_data[user_id]['state'] = 'waiting_city'
            send_message(user_id, "🏙 Сколько километров по ГОРОДУ? (число)")
        except:
            send_message(user_id, "❌ Введите число!")

    def handle_city(self, user_id, text):
        try:
            city = float(text)
            data = self.user_data[user_id]
            session_id = data['session_id']
            highway = data['highway']

            cursor.execute("INSERT INTO trips (session_id, highway, city) VALUES (?, ?, ?)", 
                          (session_id, highway, city))
            cursor.execute("UPDATE sessions SET total_highway = total_highway + ?, total_city = total_city + ? WHERE id = ?", 
                          (highway, city, session_id))
            conn.commit()

            del self.user_data[user_id]
            send_message(user_id, f"✅ Добавлено: трасса +{highway:.2f} км, город +{city:.2f} км")
            self.show_stats(user_id, session_id)
        except:
            send_message(user_id, "❌ Введите число!")

    def handle_undo_trip(self, user_id):
        session_id = get_active_session(user_id)
        if not session_id:
            send_message(user_id, "❌ Нет активной смены")
            return

        cursor.execute("SELECT id, highway, city FROM trips WHERE session_id = ? ORDER BY created_at DESC LIMIT 1", 
                      (session_id,))
        last = cursor.fetchone()
        if not last:
            send_message(user_id, "❌ Нет поездок для отмены")
            return

        trip_id, highway, city = last
        cursor.execute("UPDATE sessions SET total_highway = total_highway - ?, total_city = total_city - ? WHERE id = ?", 
                      (highway, city, session_id))
        cursor.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
        conn.commit()

        send_message(user_id, f"❌ Отменена последняя поездка (трасса {highway:.2f} км, город {city:.2f} км)")
        self.show_stats(user_id, session_id)

    def handle_refuel(self, user_id):
        session_id = get_active_session(user_id)
        if not session_id:
            send_message(user_id, "❌ Нет активной смены. Напишите /start")
            return

        self.user_data[user_id] = {'state': 'waiting_refuel', 'session_id': session_id}
        send_message(user_id, "⛽ Сколько литров заправили?")

    def handle_refuel_save(self, user_id, text):
        try:
            liters = float(text)
            data = self.user_data[user_id]
            session_id = data['session_id']

            cursor.execute("UPDATE sessions SET total_refueled = total_refueled + ? WHERE id = ?", 
                          (liters, session_id))
            conn.commit()

            del self.user_data[user_id]
            send_message(user_id, f"✅ Заправлено {liters:.2f} л")
            self.show_stats(user_id, session_id)
        except:
            send_message(user_id, "❌ Введите число!")

    def handle_end_shift(self, user_id):
        session_id = get_active_session(user_id)

        if not session_id:
            send_message(user_id, "❌ Нет активной смены. Напишите /start")
            return

        s = get_session_summary(session_id)
        if not s:
            return

        balance = get_balance(user_id)
        if balance < PRICE_PER_SHIFT:
            send_message(user_id,
                f"❌ Недостаточно средств для завершения смены.\n"
                f"Ваш баланс: {balance:.2f} руб\n"
                f"Стоимость смены: {PRICE_PER_SHIFT} руб\n\n"
                f"Смена не будет сохранена. Пополните баланс.")
            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            cursor.execute("DELETE FROM trips WHERE session_id = ?", (session_id,))
            conn.commit()
            return

        end_mileage = s["start_mileage"] + s["total_km"]
        update_balance(user_id, -PRICE_PER_SHIFT)

        cursor.execute("UPDATE sessions SET is_active = 0, was_paid = 1, ended_at = CURRENT_TIMESTAMP WHERE id = ?", 
                      (session_id,))
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

✅ Смена завершена. Для новой смены напишите /start
"""
        send_message(user_id, report, get_main_keyboard())

    # ========== АДМИН-ФУНКЦИИ ==========
    def admin_panel(self, user_id):
        if not is_admin(user_id):
            send_message(user_id, "❌ У вас нет доступа")
            return
        send_message(user_id, "👨‍💼 Админ-панель\n\nВыберите действие:", get_admin_keyboard())

    def admin_stats(self, user_id):
        if not is_admin(user_id):
            return
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
            f"💸 Задолженность: {abs(debt):.2f} руб")

    def admin_export_excel(self, user_id):
        if not is_admin(user_id):
            return
        
        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Смены"
            
            # Заголовки
            headers = ["ID смены", "Водитель", "Автомобиль", "Начальный пробег", 
                      "Трасса (км)", "Город (км)", "Всего (км)", "Топливо (л)", 
                      "Стартовое топливо", "Заправлено", "Остаток", "Дата"]
            ws.append(headers)
            
            cursor.execute("""
                SELECT s.id, s.user_id, s.car_name, s.start_mileage, 
                       s.total_highway, s.total_city, 
                       s.start_fuel, s.total_refueled,
                       s.created_at
                FROM sessions s
                WHERE s.was_paid = 1
                ORDER BY s.created_at DESC
            """)
            
            for row in cursor.fetchall():
                session_id, user_id, car_name, start_mileage, total_hw, total_city, start_fuel, total_refueled, created_at = row
                username = get_user_name(user_id)
                total_km = total_hw + total_city
                fuel_used = get_session_summary(session_id)['fuel_used'] if get_session_summary(session_id) else 0
                remaining = start_fuel + total_refueled - fuel_used
                
                ws.append([
                    session_id, username, car_name, start_mileage,
                    total_hw, total_city, total_km,
                    fuel_used, start_fuel, total_refueled, remaining,
                    created_at
                ])
            
            # Сохраняем в BytesIO
            output = BytesIO()
            wb.save(output)
            output.seek(0)
            
            # Загружаем файл на сервер VK
            upload = vk_api.VkUpload(vk_session)
            doc = upload.document(output, "отчет_по_сменам.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            send_message(user_id, "📥 Отчет сформирован", attachment=f"doc{doc['owner_id']}_{doc['id']}")
            
        except Exception as e:
            send_message(user_id, f"❌ Ошибка при создании отчета: {str(e)}")

    def admin_add_driver_start(self, user_id):
        if not is_admin(user_id):
            return
        send_message(user_id, "Введите ID пользователя ВК (число):")
        self.user_data[user_id] = {'state': 'admin_add_driver'}

    def admin_add_driver(self, user_id, text):
        try:
            new_user_id = int(text)
            username = get_user_name(new_user_id)
            register_driver(new_user_id, username)
            send_message(user_id, f"✅ Водитель {username} (ID: {new_user_id}) добавлен. Баланс: 0 руб")
        except:
            send_message(user_id, "❌ Ошибка. Введите числовой ID")
        del self.user_data[user_id]

    def admin_block_driver_start(self, user_id):
        if not is_admin(user_id):
            return
        send_message(user_id, "Введите ID пользователя ВК для блокировки:")
        self.user_data[user_id] = {'state': 'admin_block_driver'}

    def admin_block_driver(self, user_id, text):
        try:
            block_user_id = int(text)
            cursor.execute("UPDATE drivers SET is_blocked = 1 WHERE user_id = ?", (block_user_id,))
            conn.commit()
            send_message(user_id, f"✅ Водитель {block_user_id} заблокирован")
        except:
            send_message(user_id, "❌ Ошибка")
        del self.user_data[user_id]

    def admin_topup_start(self, user_id):
        if not is_admin(user_id):
            return
        send_message(user_id, "Введите ID пользователя ВК:")
        self.user_data[user_id] = {'state': 'admin_topup_user'}

    def admin_topup_user(self, user_id, text):
        try:
            target_user_id = int(text)
            self.user_data[user_id] = {'state': 'admin_topup_amount', 'topup_user': target_user_id}
            send_message(user_id, "Введите сумму пополнения (руб):")
        except:
            send_message(user_id, "❌ Ошибка. Введите числовой ID")
            del self.user_data[user_id]

    def admin_topup_amount(self, user_id, text):
        try:
            amount = float(text)
            data = self.user_data[user_id]
            target_user_id = data['topup_user']
            update_balance(target_user_id, amount)
            cursor.execute("INSERT INTO payments (user_id, amount, admin_id) VALUES (?, ?, ?)", 
                          (target_user_id, amount, user_id))
            conn.commit()
            new_balance = get_balance(target_user_id)
            send_message(user_id, f"✅ Баланс пополнен на {amount:.2f} руб\nТекущий баланс: {new_balance:.2f} руб")
            # Уведомление пользователю
            username = get_user_name(target_user_id)
            send_message(target_user_id, f"💰 Ваш баланс пополнен на {amount:.2f} руб\nТекущий баланс: {new_balance:.2f} руб")
        except:
            send_message(user_id, "❌ Ошибка. Введите сумму")
        del self.user_data[user_id]

    def admin_car_norms(self, user_id):
        if not is_admin(user_id):
            return
        cursor.execute("SELECT name, norm_highway, norm_city FROM cars")
        cars = cursor.fetchall()
        text = "🚗 Нормы расхода топлива:\n\n"
        for name, hw, city in cars:
            text += f"• {name}: трасса {hw:.2f} л/100км, город {city:.2f} л/100км\n"
        text += "\nДля изменения норм напишите:\n`/set_norm Газель трасса 13.50`\nили\n`/set_norm УАЗ город 19.00`"
        send_message(user_id, text)

    def admin_set_norm(self, user_id, text):
        if not is_admin(user_id):
            send_message(user_id, "❌ Нет доступа")
            return
        try:
            parts = text.split()
            if len(parts) != 4:
                send_message(user_id, "❌ /set_norm Газель трасса 13.50")
                return
            _, car_name, type_norm, value = parts
            value = float(value)
            if type_norm.lower() == "трасса":
                cursor.execute("UPDATE cars SET norm_highway = ? WHERE name = ?", (value, car_name))
            elif type_norm.lower() == "город":
                cursor.execute("UPDATE cars SET norm_city = ? WHERE name = ?", (value, car_name))
            else:
                send_message(user_id, "❌ Укажите 'трасса' или 'город'")
                return
            conn.commit()
            send_message(user_id, f"✅ Для {car_name} установлена норма {type_norm}: {value:.2f} л/100км")
        except:
            send_message(user_id, "❌ Ошибка. Пример: /set_norm Газель трасса 13.50")

    def admin_broadcast_start(self, user_id):
        if not is_admin(user_id):
            return
        send_message(user_id, "Введите сообщение для рассылки:")
        self.user_data[user_id] = {'state': 'admin_broadcast'}

    def admin_broadcast(self, user_id, text):
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
        del self.user_data[user_id]

    def admin_list_drivers(self, user_id):
        if not is_admin(user_id):
            return
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
            send_message(user_id, text)

    def handle_help(self, user_id):
        send_message(user_id,
            "📋 Команды бота:\n\n"
            "/start - начать новую смену\n"
            "/balance - проверить баланс\n"
            "/help - эта справка\n\n"
            "Во время смены:\n"
            "🚗 Выбрать авто - сменить автомобиль\n"
            "➕ Поездка - добавить поездку\n"
            "⛽ Заправился - добавить заправку\n"
            "↩️ Отменить последнюю - отменить последнюю поездку\n"
            "✅ Закончить смену - завершить смену\n"
            "💰 Баланс - проверить баланс")

    def process_message(self, event):
        user_id = event.user_id
        text = event.text
        
        # Обработка команд
        if text == "/start":
            self.handle_start(user_id)
            return
            
        if text == "/balance" or text == "💰 Баланс":
            self.show_balance(user_id)
            return
            
        if text == "/help":
            self.handle_help(user_id)
            return
            
        if text == "/admin":
            self.admin_panel(user_id)
            return

        # Проверка блокировки
        if is_driver_blocked(user_id):
            send_message(user_id, "❌ Ваш аккаунт заблокирован")
            return

        # Обработка состояний
        state = self.user_data.get(user_id, {}).get('state')
        
        if state == 'waiting_mileage':
            self.handle_mileage(user_id, text)
            return
        elif state == 'waiting_fuel':
            self.handle_fuel(user_id, text)
            return
        elif state == 'waiting_highway':
            self.handle_highway(user_id, text)
            return
        elif state == 'waiting_city':
            self.handle_city(user_id, text)
            return
        elif state == 'waiting_refuel':
            self.handle_refuel_save(user_id, text)
            return
        elif state == 'admin_add_driver':
            self.admin_add_driver(user_id, text)
            return
        elif state == 'admin_block_driver':
            self.admin_block_driver(user_id, text)
            return
        elif state == 'admin_topup_user':
            self.admin_topup_user(user_id, text)
            return
        elif state == 'admin_topup_amount':
            self.admin_topup_amount(user_id, text)
            return
        elif state == 'admin_broadcast':
            self.admin_broadcast(user_id, text)
            return

        # Обработка кнопок (содержат payload)
        if event.payload:
            payload = event.payload
            if 'car' in payload:
                self.handle_car_selection(user_id, payload['car'])
                return

        # Обработка текстовых кнопок
        if text == "🚗 Выбрать авто":
            self.handle_select_car(user_id)
        elif text == "➕ Поездка":
            self.handle_add_trip(user_id)
        elif text == "↩️ Отменить последнюю":
            self.handle_undo_trip(user_id)
        elif text == "⛽ Заправился":
            self.handle_refuel(user_id)
        elif text == "✅ Закончить смену":
            self.handle_end_shift(user_id)
        # Админ-кнопки
        elif text == "📊 Статистика":
            self.admin_stats(user_id)
        elif text == "📥 Выгрузить Excel":
            self.admin_export_excel(user_id)
        elif text == "➕ Добавить водителя":
            self.admin_add_driver_start(user_id)
        elif text == "❌ Заблокировать водителя":
            self.admin_block_driver_start(user_id)
        elif text == "💰 Пополнить баланс":
            self.admin_topup_start(user_id)
        elif text == "🚗 Нормы расхода":
            self.admin_car_norms(user_id)
        elif text == "📢 Рассылка":
            self.admin_broadcast_start(user_id)
        elif text == "📋 Список водителей":
            self.admin_list_drivers(user_id)
        # Команда установки нормы
        elif text.startswith("/set_norm"):
            self.admin_set_norm(user_id, text)

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    bot = VKBot()
    print("✅ VK Бот запущен")
    print("Нажмите Ctrl+C для остановки")
    
    while True:
        try:
            for event in longpoll.listen():
                if event.type == VkBotEventType.MESSAGE_NEW and event.message.text:
                    bot.process_message(event.message)
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)
