import os
import asyncio
import logging
from datetime import datetime, date, timedelta
import pytz
import re

from telegram import Bot
from telegram.error import TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
load_dotenv()

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
CHAT_ID          = os.getenv("TELEGRAM_CHAT_ID")
SPREADSHEET_ID   = os.getenv("GOOGLE_SPREADSHEET_ID")
SHEET_NAME       = os.getenv("SHEET_NAME", "Aniversários")
TIMEZONE         = os.getenv("TIMEZONE", "America/Sao_Paulo")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

COL_NOME = int(os.getenv("COL_NOME", 0))
COL_DATA = int(os.getenv("COL_DATA", 1))
COL_SEXO = int(os.getenv("COL_SEXO", 2))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# MENSAGENS
# ──────────────────────────────────────────────

def mensagem_lembrete(nome: str) -> str:
    """Enviada às 23h do dia ANTERIOR ao aniversário."""
    return (
        f"🔔 Lembrete de aniversário!\n\n"
        f"Amanhã é aniversário de *{nome.upper()}*! 🎂🎉"
    )


def mensagem_aniversario(aniversariantes: list[dict]) -> str:
    """
    Recebe lista de dicts: [{'nome': 'João', 'sexo': 'M'}, ...]
    Ordena: masculinos primeiro, depois femininos.
    Retorna a mensagem correta conforme quantidade e sexo.
    """
    # Ordenar: M primeiro, F depois
    ordenados = sorted(aniversariantes, key=lambda p: (0 if p.get('sexo','M').upper() == 'M' else 1))

    # ── Um aniversariante ──
    if len(ordenados) == 1:
        pessoa = ordenados[0]
        nome   = pessoa['nome']
        sexo   = pessoa.get('sexo', 'M').strip().upper()

        if sexo == 'F':
            return (
                f"Paz do Senhor!\n\n"
                f"Hoje, celebramos o aniversário da Ir. *{nome.upper()}*. "
                f"Louvamos a Deus por sua vida e por tudo que Ele tem feito.\n\n"
                f"Parabéns, irmã! Que o Senhor lhe conceda saúde, paz e forças para prosseguir, "
                f"e que seus pensamentos e caminhos estejam sempre alinhados à vontade de Deus.\n\n"
                f"Felicidades e bênçãos sem medida!"
            )
        else:
            return (
                f"Paz do Senhor!\n\n"
                f"Hoje, celebramos o aniversário do Ir. *{nome.upper()}*. "
                f"Louvamos a Deus por sua vida e por tudo que Ele tem feito.\n\n"
                f"Parabéns, irmão! Que o Senhor lhe conceda saúde, paz e forças para prosseguir, "
                f"e que seus pensamentos e caminhos estejam sempre alinhados à vontade de Deus.\n\n"
                f"Felicidades e bênçãos sem medida!"
            )

    # ── Dois ou mais aniversariantes ──
    nomes_fmt  = " e ".join([f"*{p['nome'].upper()}*" for p in ordenados])
    sexos      = [p.get('sexo', 'M').strip().upper() for p in ordenados]
    todas_fem  = all(s == 'F' for s in sexos)

    if todas_fem:
        return (
            f"Paz do Senhor!\n\n"
            f"Hoje, celebramos os aniversários das Ir. {nomes_fmt}. "
            f"Louvamos a Deus por suas vidas e por tudo o que Ele tem feito.\n\n"
            f"Parabéns, irmãs! Que o Senhor lhes conceda saúde, paz e forças para prosseguirem, "
            f"e que seus pensamentos e caminhos estejam sempre alinhados à vontade de Deus.\n\n"
            f"Felicidades e bênçãos sem medida!"
        )
    else:
        return (
            f"Paz do Senhor!\n\n"
            f"Hoje, celebramos os aniversários dos Ir. {nomes_fmt}. "
            f"Louvamos a Deus por suas vidas e por tudo o que Ele tem feito.\n\n"
            f"Parabéns, irmãos! Que o Senhor lhes conceda saúde, paz e forças para prosseguirem, "
            f"e que seus pensamentos e caminhos estejam sempre alinhados à vontade de Deus.\n\n"
            f"Felicidades e bênçãos sem medida!"
        )

# ──────────────────────────────────────────────
# GOOGLE SHEETS
# ──────────────────────────────────────────────

def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds  = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)


def parse_date(raw: str) -> date | None:
    raw = raw.strip().lower()
    meses_pt = {
        "jan": 1, "fev": 2, "mar": 3, "abr": 4,
        "mai": 5, "jun": 6, "jul": 7, "ago": 8,
        "set": 9, "out": 10, "nov": 11, "dez": 12
    }
    m = re.match(r"(\d{1,2})/([a-zç]+)\.?", raw)
    if m:
        dia = int(m.group(1))
        mes_str = m.group(2)[:3]
        mes = meses_pt.get(mes_str)
        if mes:
            return date(date.today().year, mes, dia)
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d/%m"):
        try:
            d = datetime.strptime(raw, fmt).date()
            if fmt == "%d/%m":
                d = d.replace(year=date.today().year)
            return d
        except ValueError:
            continue
    return None


def get_birthdays(target_date: date) -> list[dict]:
    try:
        sheet = get_sheet()
        rows  = sheet.get_all_values()
    except Exception as e:
        log.error(f"Erro ao acessar planilha: {e}")
        return []

    pessoas = []
    for i, row in enumerate(rows):
        if i == 0 and row[COL_DATA].strip().lower() in ("data", "aniversário", "birthday", "(data)"):
            continue
        if len(row) <= max(COL_NOME, COL_DATA):
            continue
        nome = row[COL_NOME].strip()
        raw  = row[COL_DATA].strip()
        sexo = row[COL_SEXO].strip().upper() if len(row) > COL_SEXO else "M"
        if not nome or not raw:
            continue
        bday = parse_date(raw)
        if bday and bday.day == target_date.day and bday.month == target_date.month:
            pessoas.append({'nome': nome, 'sexo': sexo})
    return pessoas

# ──────────────────────────────────────────────
# ENVIO
# ──────────────────────────────────────────────

async def send_message(bot: Bot, text: str):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
        log.info(f"Mensagem enviada: {text[:80]}...")
    except TelegramError as e:
        log.error(f"Erro ao enviar mensagem: {e}")

# ──────────────────────────────────────────────
# JOBS
# ──────────────────────────────────────────────

async def job_lembrete_vespera(bot: Bot):
    tz     = pytz.timezone(TIMEZONE)
    amanha = datetime.now(tz).date() + timedelta(days=1)
    log.info(f"[Véspera] Verificando aniversários para {amanha}")
    pessoas = get_birthdays(amanha)
    if not pessoas:
        log.info("[Véspera] Nenhum aniversário amanhã.")
        return
    for p in pessoas:
        await send_message(bot, mensagem_lembrete(p['nome']))


async def job_parabens_dia(bot: Bot):
    tz   = pytz.timezone(TIMEZONE)
    hoje = datetime.now(tz).date()
    log.info(f"[Hoje] Verificando aniversários para {hoje}")
    pessoas = get_birthdays(hoje)
    if not pessoas:
        log.info("[Hoje] Nenhum aniversário hoje.")
        return
    await send_message(bot, mensagem_aniversario(pessoas))

# ──────────────────────────────────────────────
# MODOS DE EXECUÇÃO
# ──────────────────────────────────────────────

async def teste():
    bot = Bot(token=TELEGRAM_TOKEN)
    log.info("🧪 Modo de teste...")
    await job_lembrete_vespera(bot)
    await job_parabens_dia(bot)


async def auto():
    tz   = pytz.timezone(TIMEZONE)
    hora = datetime.now(tz).hour
    bot  = Bot(token=TELEGRAM_TOKEN)
    log.info(f"⚙️ Modo automático — hora atual: {hora}h")
    if hora >= 22 or hora < 2:
        await job_lembrete_vespera(bot)
    else:
        await job_parabens_dia(bot)


async def main():
    log.info("🤖 Bot de aniversários iniciando...")
    bot = Bot(token=TELEGRAM_TOKEN)
    me  = await bot.get_me()
    log.info(f"Conectado como @{me.username}")

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        job_lembrete_vespera,
        trigger=CronTrigger(hour=23, minute=0, timezone=TIMEZONE),
        args=[bot], id="lembrete_vespera", replace_existing=True,
    )
    hora_parabens = int(os.getenv("HORA_PARABENS", 8))
    scheduler.add_job(
        job_parabens_dia,
        trigger=CronTrigger(hour=hora_parabens, minute=0, timezone=TIMEZONE),
        args=[bot], id="parabens_dia", replace_existing=True,
    )
    scheduler.start()
    log.info(f"✅ Agendador ativo. Véspera: 23h | Parabéns: {hora_parabens}h | Fuso: {TIMEZONE}")
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot encerrado.")
        scheduler.shutdown()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "teste":
        asyncio.run(teste())
    elif cmd == "auto":
        asyncio.run(auto())
    else:
        asyncio.run(main())
