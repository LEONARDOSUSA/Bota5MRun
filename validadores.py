import ta
import pandas as pd
import requests
from datetime import datetime, timedelta
import pytz

# 🔐 Verifica claves de Alpaca + acceso a datos
def verificar_claves_y_datos(api_key, secret_key):
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key
    }

    try:
        clock = requests.get("https://paper-api.alpaca.markets/v2/clock", headers=headers)
        if clock.status_code != 200:
            print(f"❌ Error con claves de trading: {clock.status_code}")
            return False
    except Exception as e:
        print(f"🚫 Error conectando a clock: {e}")
        return False

    try:
        eastern = pytz.timezone("US/Eastern")
        ayer = datetime.now(tz=eastern) - timedelta(days=1)
        start = ayer.replace(hour=9, minute=30, second=0).isoformat()
        end = ayer.replace(hour=9, minute=45, second=0).isoformat()

        params = {
            "timeframe": "15Min",
            "adjustment": "raw",
            "start": start,
            "end": end
        }

        resp = requests.get("https://data.alpaca.markets/v2/stocks/AAPL/bars", headers=headers, params=params)
        if resp.status_code != 200:
            print(f"❌ Error con datos de mercado: {resp.status_code}")
            return False
    except Exception as e:
        print(f"🚫 Error accediendo a datos: {e}")
        return False

    print("✅ Verificación de claves y datos completada.")
    return True

# 📏 Evalúa si vela tiene cuerpo dominante
def cuerpo_dominante(vela, umbral=0.65):
    cuerpo = abs(vela["close"] - vela["open"])
    rango = vela["high"] - vela["low"]
    if rango == 0:
        return False
    proporcion = cuerpo / rango
    return proporcion >= umbral

# 📉 Valida alineación SMA en un marco dado
def validar_sma(df, direccion, marco):
    try:
        sma20 = ta.trend.sma_indicator(df["close"], window=20)
        sma30 = ta.trend.sma_indicator(df["close"], window=30)
        p = df["close"].iloc[-1]
        s20 = sma20.iloc[-1]
        s30 = sma30.iloc[-1]
        print(f"📏 SMA {marco} ➝ Precio={round(p,2)}, SMA20={round(s20,2)}, SMA30={round(s30,2)} ➝ ", end="")

        if pd.isna(s20) or pd.isna(s30):
            print("⚠️ SMA incompleta ➝ marco omitido")
            return False

        if direccion == "CALL" and p > s20 and p > s30 and s20 > s30:
            print("✅ alineadas")
            return True
        elif direccion == "PUT" and p < s20 and p < s30 and s20 < s30:
            print("✅ alineadas")
            return True
        else:
            print("❌ no alineadas")
            return False
    except Exception as e:
        print(f"📏 SMA {marco} ➝ ⚠️ error: {e}")
        return False

# 🧭 Detecta último cruce MACD
def detectar_ultimo_cruce_macd(df):
    for i in range(len(df) - 1, 0, -1):
        m0, s0 = df["macd"].iloc[i - 1], df["signal"].iloc[i - 1]
        m1, s1 = df["macd"].iloc[i], df["signal"].iloc[i]
        if m0 < s0 and m1 > s1:
            return df.index[i], "CALL"
        elif m0 > s0 and m1 < s1:
            return df.index[i], "PUT"
    return None, None

# 📊 Diagnóstico MACD multiframe
def diagnostico_macd(api, ticker, marco, momento, direccion, tz):
    try:
        ts = momento.replace(second=0)
        ajuste = {"5Min": 5, "15Min": 15}
        if marco in ajuste:
            ts -= timedelta(minutes=ts.minute % ajuste[marco])
        ts -= timedelta(minutes=1)

        inicio = tz.localize((ts - timedelta(minutes=600)).replace(tzinfo=None))
        fin = tz.localize(ts.replace(tzinfo=None))
        df = api.get_bars(ticker, marco, start=inicio.isoformat(), end=fin.isoformat()).df
        df = df.tz_convert(tz).dropna()

        if len(df) < 35:
            print(f"· {marco}: ❌ Datos insuficientes — descartado")
            return False

        macd = ta.trend.MACD(df["close"])
        df["macd"], df["signal"] = macd.macd(), macd.macd_signal()
        df = df.dropna()

        if marco == "15Min":
            cruce_time, tipo_cruce = detectar_ultimo_cruce_macd(df)
            if cruce_time:
                minutos_pasados = (momento - cruce_time).total_seconds() / 60
                print(f"🧭 Último cruce MACD ➝ {cruce_time.strftime('%H:%M')} ({round(minutos_pasados)} min atrás)")
                if minutos_pasados > 180:
                    print("⛔ Cruce MACD caducado ➝ marco 15Min ignorado")
                    return False

        m1, s1 = df["macd"].iloc[-1], df["signal"].iloc[-1]
        return m1 > s1 if direccion == "CALL" else m1 < s1

    except Exception as e:
        print(f"· {marco}: ⚠️ Error técnico → {e}")
        return False

# 🧮 Evaluación técnica con puntaje institucional
def evaluar_calidad_senal(api, ticker, fecha, direccion, momento, tz):
    try:
        df = api.get_bars(
            ticker,
            "1Min",
            start=(momento - timedelta(minutes=30)).isoformat(),
            end=momento.isoformat()
        ).df.tz_convert(tz).dropna()

        vela = df.iloc[-1]
        cuerpo = abs(vela["close"] - vela["open"])
        rango = vela["high"] - vela["low"]
        pct = cuerpo / rango if rango > 0 else 0

        macd = ta.trend.MACD(df["close"])
        impulso = abs(macd.macd().iloc[-1] - macd.macd_signal().iloc[-1])

        sma20 = ta.trend.sma_indicator(df["close"], window=20).iloc[-1]
        dif_sma = abs(vela["close"] - sma20)

        puntaje = round(pct * 2 + impulso + dif_sma * 0.5, 4)

        if puntaje >= 4.0:
            nivel = "→ Señal institucional de élite"
        elif puntaje >= 3.5:
            nivel = "→ Señal táctica limpia"
        elif puntaje >= 2.5:
            nivel = "→ Señal decente (vigilar continuación)"
        else:
            nivel = "→ Señal débil (probable congestión)"

        return f"\n🧮 *Evaluación institucional:*\n{nivel}\n⚖️ *Puntuación técnica:* `{puntaje}`"
    except Exception as e:
        return f"\n⚠️ *Evaluación fallida:* {e}"
