import requests
from bs4 import BeautifulSoup
import re
import time
import urllib3

# Отключаем предупреждения о неверном SSL сертификате
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ВАШИ ДАННЫЕ ДЛЯ ВХОДА
USERNAME = ""  # Замените на ваш логин
PASSWORD = ""  # Замените на ваш пароль

BASE_URL = "https://lms.mipt.ru"
LOGIN_URL = f"{BASE_URL}/login/index.php"
QUIZ_BASE_URL = f"{BASE_URL}/mod/quiz/attempt.php"

# Параметры конкретного теста
ATTEMPT_ID = ""
CMID = ""
TOTAL_PAGES = 25  # Количество страниц с вопросами
# =============================================

def login(session):
    """Выполняет вход в систему и возвращает True при успехе"""
    print("🔐 Выполняется вход...")
    
    # 1. Получаем страницу входа, чтобы найти скрытые токены (logintoken)
    try:
        resp = session.get(LOGIN_URL, verify=False)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Ищем токен logintoken
        token_input = soup.find('input', {'name': 'logintoken'})
        logintoken = token_input['value'] if token_input else ''
        
        # Формируем данные для POST-запроса
        payload = {
            'username': USERNAME,
            'password': PASSWORD,
            'logintoken': logintoken
        }
        
        # 2. Отправляем данные для входа
        resp = session.post(LOGIN_URL, data=payload, verify=False)
        
        # Проверка успеха: ищем ссылку выхода или имя пользователя в ответе
        if "logout.php" in resp.text or USERNAME.lower() in resp.text.lower():
            print("✅ Вход выполнен успешно!")
            return True
        else:
            print("❌ Ошибка входа. Проверьте логин и пароль.")
            return False
            
    except Exception as e:
        print(f"⚠️ Ошибка при входе: {e}")
        return False

def get_page_content(session, page_num):
    """Загрузка HTML конкретной страницы теста"""
    params = {
        'attempt': ATTEMPT_ID,
        'cmid': CMID,
    }
    # Если это не первая страница (страница 0), добавляем параметр page
    if page_num > 0:
        params['page'] = str(page_num)
        
    try:
        resp = session.get(QUIZ_BASE_URL, params=params, verify=False)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"⚠️ Ошибка загрузки страницы {page_num}: {e}")
        return None

def parse_multichoice_question(block):
    """Парсинг обычного вопроса с выбором одного/нескольких ответов"""
    q_data = {}
    
    # 1. Номер вопроса
    qno_span = block.find('span', class_='qno')
    if qno_span:
        q_data['number'] = qno_span.get_text(strip=True)
    else:
        return None
        
    # 2. Текст вопроса
    qtext_div = block.find('div', class_='qtext')
    if qtext_div:
        for tag in qtext_div.find_all(['script', 'style']):
            tag.decompose()
        q_data['text'] = re.sub(r'\s+', ' ', qtext_div.get_text(separator=' ', strip=True))
    else:
        q_data['text'] = "Текст не найден"
        
    # 3. Варианты ответов (обычные radio/checkbox)
    answers = []
    answer_div = block.find('div', class_='answer')
    if answer_div:
        options = answer_div.find_all('div', class_=re.compile(r'^r\d+$'))
        for opt in options:
            label = opt.find('label')
            if label:
                for span in label.find_all('span', class_='answernumber'):
                    span.decompose()
                ans_text = re.sub(r'\s+', ' ', label.get_text(strip=True))
                if ans_text:
                    answers.append(ans_text)
    
    q_data['answers'] = answers
    q_data['type'] = 'Выбор ответа'
    return q_data

def parse_matching_question(block):
    """Парсинг вопроса на сопоставление (таблица с select)"""
    q_data = {}
    
    # 1. Номер вопроса
    qno_span = block.find('span', class_='qno')
    if qno_span:
        q_data['number'] = qno_span.get_text(strip=True)
    else:
        return None
        
    # 2. Текст вопроса
    qtext_div = block.find('div', class_='qtext')
    if qtext_div:
        for tag in qtext_div.find_all(['script', 'style']):
            tag.decompose()
        q_data['text'] = re.sub(r'\s+', ' ', qtext_div.get_text(separator=' ', strip=True))
    else:
        q_data['text'] = "Текст не найден"

    # 3. Парсинг таблицы сопоставления
    matches = []
    table = block.find('table')
    if table:
        rows = table.find_all('tr')
        for row in rows:
            # Первая ячейка - утверждение/вопрос
            td_text = row.find('td', class_='text')
            # Вторая ячейка - управление (select)
            td_control = row.find('td', class_='control')
            
            if td_text and td_control:
                # Получаем текст утверждения
                statement = re.sub(r'\s+', ' ', td_text.get_text(strip=True))
                
                # Получаем варианты из select
                select = td_control.find('select')
                options = []
                if select:
                    for option in select.find_all('option'):
                        opt_text = option.get_text(strip=True)
                        # Пропускаем пустые или служебные опции типа "Выберите..."
                        if opt_text and opt_text != "Выберите...":
                            options.append(opt_text)
                
                if statement:
                    matches.append({
                        'statement': statement,
                        'options': options
                    })
    
    q_data['matches'] = matches
    q_data['type'] = 'Сопоставление'
    return q_data

def parse_and_print_questions(html, page_num):
    """Основная функция парсинга, определяющая тип вопроса"""
    if not html:
        return
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Ищем блоки вопросов. Класс может быть que multichoice, que match и т.д.
    question_blocks = soup.find_all('div', class_=re.compile(r'^que\s+'))
    
    if not question_blocks:
        # Иногда структура может отличаться, попробуем найти по ID вопроса
        pass

    for block in question_blocks:
        # Определяем тип вопроса по классам блока
        # Обычно match вопросы имеют класс 'que match' или содержат таблицу внутри
        is_matching = bool(block.find('table')) or 'match' in block.get('class', [])
        
        if is_matching:
            q = parse_matching_question(block)
        else:
            q = parse_multichoice_question(block)
            
        if q:
            print("-" * 50)
            print(f"Вопрос №{q['number']} ({q['type']})")
            print(f"{q['text']}")
            
            if q['type'] == 'Выбор ответа':
                print("\nВарианты ответов:")
                for i, ans in enumerate(q['answers'], 1):
                    print(f"  {i}. {ans}")
                    
            elif q['type'] == 'Сопоставление':
                print("\nПары для сопоставления:")
                for i, pair in enumerate(q['matches'], 1):
                    print(f"\n  {i}. Утверждение: {pair['statement']}")
                    if pair['options']:
                        print("     Доступные варианты:")
                        for opt in pair['options']:
                            print(f"       - {opt}")
            print() # Пустая строка

def main():
    # Создаем сессию для сохранения cookies
    session = requests.Session()
    # Добавляем заголовки, чтобы сервер думал, что мы браузер
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })
    
    # 1. Авторизация
    if not login(session):
        return
    
    print("\n📄 Начинаю парсинг вопросов...\n")
    
    # 2. Цикл по всем страницам теста
    for page_num in range(TOTAL_PAGES):
        print(f"   Обработка страницы {page_num + 1}/{TOTAL_PAGES}...", end="\r")
        
        html = get_page_content(session, page_num)
        if html:
            parse_and_print_questions(html, page_num)
        
        # Небольшая пауза, чтобы не нагружать сервер
        time.sleep(0.5)
        
    print("\n\n✅ Парсинг завершен!")

if __name__ == "__main__":
    main()