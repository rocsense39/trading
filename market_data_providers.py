"""
Market data provider layer for XTB ETF Portfolio Manager V3.1
=============================================================

Goal: switch between XTB xAPI and Yahoo Finance without changing portfolio logic.

Environment variables for XTB:
    XTB_USER_ID      your XTB account login / userId
    XTB_PASSWORD     your XTB password
    XTB_MODE         demo or real, default demo

Config example:
    "data_provider": {
        "primary": "xtb",
        "fallback": "yahoo",
        "xtb": {"mode": "demo", "timeout_seconds": 15},
        "yahoo": {"enabled": true}
    }

Notes:
- XTB historical chart candles are returned through xAPI getChartRangeRequest.
- The adapter returns a normalized pandas DataFrame with Open, High, Low, Close, Volume.
- If XTB fails or lacks a symbol, the DataManager can fall back to Yahoo automatically.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

MKT_TZ = ZoneInfo("Europe/Berlin")


def interval_to_minutes(interval: str) -> int:
    mapping = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "60m": 60, "4h": 240, "1d": 1440, "1wk": 10080,
    }
    if interval not in mapping:
        raise ValueError(f"Unsupported interval {interval!r}. Use one of {sorted(mapping)}")
    return mapping[interval]


def period_to_start_ms(period: str) -> int:
    now = datetime.now(timezone.utc)
    p = period.lower().strip()
    if p.endswith("mo"):
        months = int(p[:-2])
        start = now - timedelta(days=months * 31)
    elif p.endswith("y"):
        years = int(p[:-1])
        start = now - timedelta(days=years * 366)
    elif p.endswith("d"):
        days = int(p[:-1])
        start = now - timedelta(days=days)
    else:
        start = now - timedelta(days=270)
    return int(start.timestamp() * 1000)


class MarketDataProvider(Protocol):
    name: str

    def get_ohlcv(self, symbol: str, *, period: str, interval: str) -> pd.DataFrame:
        ...


@dataclass
class YahooProvider:
    name: str = "yahoo"

    def get_ohlcv(self, symbol: str, *, period: str, interval: str) -> pd.DataFrame:
        try:
            df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
        except Exception as exc:
            raise RuntimeError(f"Yahoo download failed for {symbol}: {exc}") from exc
        return normalize_yahoo_df(df)


class XTBXApiClient:
    def __init__(self, *, mode: str = "demo", timeout_seconds: int = 15) -> None:
        mode = (mode or os.getenv("XTB_MODE") or "demo").lower()
        self.host = "xapi.xtb.com"
        self.port = 5124 if mode == "real" else 5125
        self.timeout_seconds = timeout_seconds
        self.sock: ssl.SSLSocket | None = None
        self.stream_session_id: str | None = None

    def connect(self) -> None:
        if self.sock is not None:
            return
        raw = socket.create_connection((self.host, self.port), timeout=self.timeout_seconds)
        context = ssl.create_default_context()
        self.sock = context.wrap_socket(raw, server_hostname=self.host)
        self.sock.settimeout(self.timeout_seconds)

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _send(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.connect()
        assert self.sock is not None
        self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        chunks: list[bytes] = []
        while True:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("XTB socket closed unexpectedly")
            chunks.append(chunk)
            raw = b"".join(chunks).decode("utf-8", errors="replace")
            # xAPI responses are JSON objects; parse as soon as a full object arrives.
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                continue

    def login(self) -> None:
        user_id = os.getenv("XTB_USER_ID", "").strip()
        password = os.getenv("XTB_PASSWORD", "").strip()
        if not user_id or not password:
            raise RuntimeError("Missing XTB_USER_ID or XTB_PASSWORD environment variable")
        response = self._send({"command": "login", "arguments": {"userId": user_id, "password": password}})
        if not response.get("status"):
            raise RuntimeError(f"XTB login failed: {response}")
        self.stream_session_id = response.get("streamSessionId")

    def command(self, command: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._send({"command": command, "arguments": arguments or {}})
        if not response.get("status"):
            raise RuntimeError(f"XTB command {command} failed: {response}")
        return response.get("returnData", {})


@dataclass
class XTBProvider:
    mode: str = "demo"
    timeout_seconds: int = 15
    name: str = "xtb"

    def __post_init__(self) -> None:
        self.client = XTBXApiClient(mode=self.mode, timeout_seconds=self.timeout_seconds)
        self._logged_in = False

    def ensure_login(self) -> None:
        if not self._logged_in:
            self.client.login()
            self._logged_in = True

    def get_ohlcv(self, symbol: str, *, period: str, interval: str) -> pd.DataFrame:
        self.ensure_login()
        minutes = interval_to_minutes(interval)
        start = period_to_start_ms(period)
        data = self.client.command("getChartRangeRequest", {
            "info": {
                "period": minutes,
                "start": start,
                "symbol": symbol,
                "ticks": 0,
            }
        })
        rows = data.get("rateInfos", [])
        if not rows:
            raise RuntimeError(f"XTB returned no candles for {symbol}")
        digits = int(data.get("digits", 2))
        scale = 10 ** digits
        records: list[dict[str, float | pd.Timestamp]] = []
        for r in rows:
            open_price = float(r["open"]) / scale
            records.append({
                "Datetime": pd.to_datetime(int(r["ctm"]), unit="ms", utc=True).tz_convert(MKT_TZ),
                "Open": open_price,
                "High": open_price + float(r.get("high", 0)) / scale,
                "Low": open_price + float(r.get("low", 0)) / scale,
                "Close": open_price + float(r.get("close", 0)) / scale,
                "Volume": float(r.get("vol", 0)),
            })
        df = pd.DataFrame.from_records(records).set_index("Datetime").sort_index()
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def normalize_yahoo_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        raise RuntimeError("empty Yahoo response")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns=str.title).copy()
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"missing OHLCV columns: {sorted(required - set(df.columns))}")
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(MKT_TZ)
    else:
        df.index = df.index.tz_convert(MKT_TZ)
    return df


class DataManager:
    def __init__(self, config: dict[str, Any]) -> None:
        provider_cfg = config.get("data_provider", {})
        primary_name = provider_cfg.get("primary", "yahoo")
        fallback_name = provider_cfg.get("fallback", "yahoo")
        self.primary = self._build_provider(primary_name, provider_cfg)
        self.fallback = self._build_provider(fallback_name, provider_cfg) if fallback_name != primary_name else None
        self.last_source: dict[str, str] = {}

    def _build_provider(self, name: str, provider_cfg: dict[str, Any]) -> MarketDataProvider:
        name = (name or "yahoo").lower()
        if name == "xtb":
            xtb_cfg = provider_cfg.get("xtb", {})
            return XTBProvider(
                mode=xtb_cfg.get("mode") or os.getenv("XTB_MODE") or "demo",
                timeout_seconds=int(xtb_cfg.get("timeout_seconds", 15)),
            )
        if name == "yahoo":
            return YahooProvider()
        raise ValueError(f"Unknown market data provider {name!r}")

    def symbol_for(self, meta: dict[str, Any], provider_name: str) -> str:
        if provider_name == "xtb":
            return meta.get("xtb_symbol") or meta.get("symbol")
        return meta.get("yf_symbol") or meta.get("xtb_symbol") or meta.get("symbol")

    def get_ohlcv(self, meta_or_symbol: dict[str, Any] | str, *, period: str, interval: str) -> pd.DataFrame:
        if isinstance(meta_or_symbol, dict):
            primary_symbol = self.symbol_for(meta_or_symbol, self.primary.name)
            display_key = meta_or_symbol.get("xtb_symbol") or primary_symbol
        else:
            primary_symbol = meta_or_symbol
            display_key = meta_or_symbol
        try:
            df = self.primary.get_ohlcv(primary_symbol, period=period, interval=interval)
            self.last_source[str(display_key)] = self.primary.name
            return df
        except Exception as primary_exc:
            if self.fallback is None:
                raise
            if isinstance(meta_or_symbol, dict):
                fallback_symbol = self.symbol_for(meta_or_symbol, self.fallback.name)
            else:
                fallback_symbol = meta_or_symbol
            try:
                df = self.fallback.get_ohlcv(fallback_symbol, period=period, interval=interval)
                self.last_source[str(display_key)] = f"{self.fallback.name} fallback after {self.primary.name} error: {primary_exc}"
                return df
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"Both market data providers failed for {display_key}. "
                    f"Primary error: {primary_exc}. Fallback error: {fallback_exc}"
                ) from fallback_exc
