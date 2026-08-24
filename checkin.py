import requests
import json
import os
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, asdict
from pypushdeer import PushDeer
from logging_config import init_logger


def beijing_now(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """获取北京时间字符串"""
    return datetime.now(timezone(timedelta(hours=8))).strftime(fmt)


class CheckinStatus(Enum):
    """签到状态"""

    SUCCESS = 0
    REPEAT = 1
    FAILURE = -2


class ExchangeStatus(Enum):
    """兑换状态"""

    SUCCESS = "success"  # 兑换成功
    FAILURE = "failure"  # 兑换接口返回失败
    INSUFFICIENT = "insufficient"  # 积分未达标, 未调用兑换接口
    SKIPPED = "skipped"  # 未执行兑换


class ExchangePlan(Enum):
    """兑换计划"""

    PLAN100 = "plan100"
    PLAN200 = "plan200"
    PLAN500 = "plan500"


class APIEndpoint(Enum):
    """API端点"""

    CHECKIN = "/api/user/checkin"
    STATUS = "/api/user/status"
    POINTS = "/api/user/points"
    EXCHANGE = "/api/user/exchange"


class LogEmoji:
    """日志 Emoji 常量"""

    SUCCESS = "✅"
    FAIL = "❌"
    REPEAT = "🔄"
    PENDING = "⏳"
    CHECKIN = "🎫"
    STATUS = "📊"
    POINTS = "💰"
    EXCHANGE = "🎁"
    START = "🚀"
    END = "🏁"
    COOKIE = "🍪"
    DOMAIN = "🌐"
    PUSH = "📮"
    WARNING = "⚠️ "
    ERROR = "🔴"
    INFO = "ℹ️ "


def log_method(func):
    """日志装饰器"""

    def wrapper(self, *args, **kwargs):
        method_name = func.__name__
        emoji_map = {
            "checkin": LogEmoji.CHECKIN,
            "get_status": LogEmoji.STATUS,
            "get_points": LogEmoji.POINTS,
            "exchange": LogEmoji.EXCHANGE,
        }
        emoji = emoji_map.get(method_name, LogEmoji.INFO)
        try:
            result = func(self, *args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"{LogEmoji.COOKIE}[{self.cookie_index}] {LogEmoji.DOMAIN}[{self.domain}] {LogEmoji.ERROR} {method_name} 执行失败: {e}")

            DEFAULT_ERRORS = {
                "checkin": {"status": "签到失败", "points": "0", "message": ""},
                "get_status": ("None 天", -2),
                "get_points": ("None 积分", 0),
                "exchange": ("兑换失败: 执行异常", ExchangeStatus.FAILURE),
            }

            if method_name in DEFAULT_ERRORS:
                error_template = DEFAULT_ERRORS[method_name]
                if isinstance(error_template, dict):
                    error_result = error_template.copy()
                    error_result["message"] = f"执行失败: {e}"
                    return error_result
                return error_template
            raise

    return wrapper


class Config:
    """应用配置"""

    ENV_PUSH_KEY = "PUSHDEER_SENDKEY"
    ENV_FEISHU_WEBHOOK = "FEISHU_WEBHOOK"
    ENV_COOKIES = "GLADOS_COOKIES"
    ENV_EXCHANGE_PLAN = "GLADOS_EXCHANGE_PLAN"
    ENV_DOMAINS = "GLADOS_DOMAINS"
    ENV_VERBOSE = "GLADOS_VERBOSE"

    """默认兑换计划"""
    DEFAULT_EXCHANGE_PLAN = "plan500"

    """默认是否输出详细响应"""
    DEFAULT_VERBOSE = False

    """默认域名"""
    DOMAINS = ["glados.cloud", "railgun.info"]

    """兑换计划列表: 计划 -> 所需积分"""
    EXCHANGE_PLANS = {
        ExchangePlan.PLAN100.value: 100,
        ExchangePlan.PLAN200.value: 200,
        ExchangePlan.PLAN500.value: 500,
    }

    """兑换计划对应可兑换天数"""
    EXCHANGE_PLAN_DAYS = {
        ExchangePlan.PLAN100.value: 10,
        ExchangePlan.PLAN200.value: 30,
        ExchangePlan.PLAN500.value: 100,
    }

    def __init__(self):
        self.push_key: str = ""
        self.feishu_webhook: str = ""
        self.cookies_list: List[str] = []
        self.exchange_plan: str = self.DEFAULT_EXCHANGE_PLAN
        self.domains: List[str] = list(self.DOMAINS)
        self.verbose: bool = self.DEFAULT_VERBOSE
        self._load_config()

    @property
    def required_points(self) -> int:
        """当前兑换计划所需积分"""
        return self.EXCHANGE_PLANS.get(self.exchange_plan, 500)

    @property
    def exchange_days(self) -> int:
        """当前兑换计划可兑换天数"""
        return self.EXCHANGE_PLAN_DAYS.get(self.exchange_plan, 100)

    @staticmethod
    def _normalize_domain(raw: str) -> str:
        """规范化域名, 去掉协议头与多余的斜杠"""
        domain = raw.strip()
        for prefix in ("https://", "http://"):
            if domain.lower().startswith(prefix):
                domain = domain[len(prefix) :]
                break
        return domain.strip("/").strip()

    def _load_config(self) -> None:
        """加载配置"""
        push_key_env: Optional[str] = os.environ.get(self.ENV_PUSH_KEY)
        feishu_webhook_env: Optional[str] = os.environ.get(self.ENV_FEISHU_WEBHOOK)
        raw_cookies_env: Optional[str] = os.environ.get(self.ENV_COOKIES)
        exchange_plan_env: Optional[str] = os.environ.get(self.ENV_EXCHANGE_PLAN)
        domains_env: Optional[str] = os.environ.get(self.ENV_DOMAINS)
        verbose_env: Optional[str] = os.environ.get(self.ENV_VERBOSE)

        if not push_key_env:
            self.push_key = ""
        else:
            self.push_key = push_key_env.strip()

        if not feishu_webhook_env:
            self.feishu_webhook = ""
        else:
            self.feishu_webhook = feishu_webhook_env.strip()

        if not push_key_env and not feishu_webhook_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_PUSH_KEY}' 与 '{self.ENV_FEISHU_WEBHOOK}' 均未设置, 将不发送推送。")

        if not raw_cookies_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_COOKIES}' 未设置。")
            self.cookies_list = []
        else:
            self.cookies_list = [cookie.strip() for cookie in raw_cookies_env.split("&") if cookie.strip()]
            if not self.cookies_list:
                logger.error(f"{LogEmoji.ERROR} 环境变量 '{self.ENV_COOKIES}' 已设置, 但未包含任何有效的 Cookie。")

        if not exchange_plan_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_EXCHANGE_PLAN}' 未设置，将使用默认兑换计划 {self.DEFAULT_EXCHANGE_PLAN}。")
            self.exchange_plan = self.DEFAULT_EXCHANGE_PLAN
        else:
            exchange_plan_env = exchange_plan_env.strip()
            if exchange_plan_env in self.EXCHANGE_PLANS:
                self.exchange_plan = exchange_plan_env
                logger.info(f"{LogEmoji.SUCCESS} 使用指定的兑换计划: {self.exchange_plan}")
            else:
                logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_EXCHANGE_PLAN}' 的值 '{exchange_plan_env}' 无效，将使用默认兑换计划 {self.DEFAULT_EXCHANGE_PLAN}。")
                self.exchange_plan = self.DEFAULT_EXCHANGE_PLAN

        # 域名可通过环境变量覆盖, 多个域名使用 , 分隔; 只有一个域名的账号可只填对应域名, 避免无效失败
        if domains_env:
            domains = [self._normalize_domain(d) for d in domains_env.replace("&", ",").split(",")]
            domains = [d for d in domains if d]
            if domains:
                self.domains = domains
            else:
                logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_DOMAINS}' 未解析出有效域名, 将使用默认域名 {self.DOMAINS}。")

        logger.info(f"{LogEmoji.INFO} 共加载了 {len(self.cookies_list)} 个 Cookie 用于签到。")
        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_PUSH_KEY} {'已设置' if push_key_env else '未设置'}。")
        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_FEISHU_WEBHOOK} {'已设置' if feishu_webhook_env else '未设置'}。")
        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_EXCHANGE_PLAN}: {self.exchange_plan} ({self.required_points} 积分 → {self.exchange_days} 天)。")
        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_DOMAINS}: {self.domains}。")

        if verbose_env is not None:
            verbose_env_lower = verbose_env.lower()
            if verbose_env_lower in ["true", "1", "yes", "y"]:
                self.verbose = True
            elif verbose_env_lower in ["false", "0", "no", "n"]:
                self.verbose = False
            else:
                logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_VERBOSE}' 的值 '{verbose_env}' 无效，将使用默认值 {self.DEFAULT_VERBOSE}。")

        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_VERBOSE}: {self.verbose}。")


class API:
    """API 调用"""

    CHECKIN_URL = APIEndpoint.CHECKIN.value
    STATUS_URL = APIEndpoint.STATUS.value
    POINTS_URL = APIEndpoint.POINTS.value
    EXCHANGE_URL = APIEndpoint.EXCHANGE.value

    def __init__(self, domain: str, cookie_index: int = 0, verbose: bool = False):
        self.domain: str = domain
        self.cookie_index: int = cookie_index
        self.verbose: bool = verbose
        self.headers: Dict[str, str] = self._get_headers()
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def __del__(self):
        """关闭 session"""
        self.close()

    def close(self) -> None:
        """关闭 session"""
        if hasattr(self, "session"):
            try:
                self.session.close()
            except Exception as e:
                logger.error(f"{LogEmoji.ERROR} 关闭 session 时发生错误: {e}")

    def __enter__(self):
        """进入上下文管理器"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文管理器"""
        self.close()
        return False

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "origin": f"https://{self.domain}",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
        }

    def _log(self, level: str, emoji: str, message: str, force: bool = False) -> None:
        """统一日志输出方法"""

        log_message = f"{LogEmoji.COOKIE}[{self.cookie_index}] {LogEmoji.DOMAIN}[{self.domain}] {emoji} {message}"

        if force or self.verbose:
            if level == "info":
                logger.info(log_message)
            elif level == "warning":
                logger.warning(log_message)
            elif level == "error":
                logger.error(log_message)

    def _get_full_url(self, path: str) -> str:
        """获取完整 URL"""
        return f"https://{self.domain}{path}"

    def _make_request(self, url: str, method: str, data: Optional[Dict] = None, cookies: str = "") -> Optional[requests.Response]:
        """发送 HTTP 请求"""
        session_headers = self.headers.copy()
        session_headers["cookie"] = cookies

        try:
            if method.upper() == "POST":
                response = self.session.post(url, headers=session_headers, data=data, timeout=(60, 120))
            elif method.upper() == "GET":
                response = self.session.get(url, headers=session_headers, timeout=(60, 120))
            else:
                self._log("error", LogEmoji.ERROR, f"不支持的 HTTP 方法: {method}", force=True)
                return None

            if not response.ok:
                self._log("warning", LogEmoji.WARNING, f"向 {url} 发起的请求失败，状态码 {response.status_code}。响应内容: {response.text}", force=True)
                return None
            return response
        except requests.exceptions.RequestException as e:
            self._log("error", LogEmoji.ERROR, f"向 {url} 发起请求时发生网络错误: {e}", force=True)
            return None

    def _get_checkin_data(self) -> Dict[str, str]:
        """获取签到数据"""
        return {"token": self.domain}

    @log_method
    def checkin(self, cookies: str) -> Dict[str, Union[str, CheckinStatus]]:
        """执行签到"""
        url = self._get_full_url(self.CHECKIN_URL)
        checkin_data = self._get_checkin_data()
        response = self._make_request(url, "POST", checkin_data, cookies)

        result = {
            "status": "签到失败",
            "points": "0",
            "message": "",
            "code": CheckinStatus.FAILURE,
        }

        if response:
            data = response.json()
            code = data.get("code", -2)
            message = data.get("message", "无消息字段")
            points = str(data.get("points", 0))

            if code == CheckinStatus.SUCCESS.value:
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, points : {points}, message : {message} }}")
                result["code"] = CheckinStatus.SUCCESS
                result["status"] = "签到成功"
                result["points"] = points
                result["message"] = message
            elif code == CheckinStatus.REPEAT.value:
                self._log("info", LogEmoji.REPEAT, f"{{ code : {code}, message : {message} }}", force=True)
                result["code"] = CheckinStatus.REPEAT
                result["status"] = "重复签到"
                result["points"] = "0"
                result["message"] = message
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, message : {message} }}", force=True)
                result["code"] = CheckinStatus.FAILURE
                result["status"] = "签到失败"
                result["points"] = "0"
                result["message"] = message
        else:
            self._log("warning", LogEmoji.WARNING, "签到失败", force=True)
            result["code"] = CheckinStatus.FAILURE
            result["status"] = "签到失败"
            result["message"] = "网络请求失败"

        return result

    @log_method
    def get_status(self, cookies: str) -> Tuple[str, int]:
        """获取状态"""

        url = self._get_full_url(self.STATUS_URL)
        response = self._make_request(url, "GET", cookies=cookies)

        if response:
            data = response.json()
            code = data.get("code", -2)
            left_days = data.get("data", {}).get("leftDays", None)

            if left_days is not None:
                left_days_int = int(float(left_days))
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, leftDays : {left_days_int} 天}}")
                return f"{left_days_int} 天", code
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, leftDays : {left_days} 天}}", force=True)
                return "None 天", code
        else:
            self._log("warning", LogEmoji.WARNING, "获取状态失败", force=True)
            return "None 天", -2

    @log_method
    def get_points(self, cookies: str) -> Tuple[str, int]:
        """获取积分"""
        url = self._get_full_url(self.POINTS_URL)
        response = self._make_request(url, "GET", cookies=cookies)

        if response:
            data = response.json()
            code = data.get("code", -2)
            points = data.get("points", None)

            if points is not None:
                points_int = int(float(points))
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, points : {points_int} 积分}}")
                points_str = f"{points_int} 积分"
                points_num = points_int
                return points_str, points_num
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, points : {points} 积分}}", force=True)
                return "None 积分", 0
        else:
            self._log("warning", LogEmoji.WARNING, "获取积分失败", force=True)
            return "None 积分", 0

    @log_method
    def exchange(self, cookies: str, plan: str, required_points: int) -> Tuple[str, ExchangeStatus]:
        """执行兑换"""
        url = self._get_full_url(self.EXCHANGE_URL)
        response = self._make_request(url, "POST", {"planType": plan}, cookies)

        if response:
            data = response.json()
            code = data.get("code", -2)
            message = data.get("message", "未知错误")

            if code == 0:
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, message : {message} }}", force=True)
                return f"兑换成功: {plan}", ExchangeStatus.SUCCESS
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, message : {message} }}", force=True)
                return f"兑换失败: {message}", ExchangeStatus.FAILURE
        else:
            self._log("warning", LogEmoji.WARNING, "兑换失败", force=True)
            return "兑换失败: 请求失败", ExchangeStatus.FAILURE


@dataclass()
class CheckinResult:
    """签到结果"""

    cookie_index: int
    domain: str
    status: str = "签到失败"
    points: str = "0"
    days: str = "None"
    points_total: str = "None"
    exchange: str = "未兑换"
    code: CheckinStatus = CheckinStatus.FAILURE  # 0: 成功, 1: 重复, -2: 失败
    exchange_code: ExchangeStatus = ExchangeStatus.SKIPPED

    def to_dict(self) -> Dict[str, Union[str, CheckinStatus]]:
        result_dict = asdict(self)
        return result_dict


@dataclass()
class PushPayload:
    """推送内容"""

    title: str
    text: str  # 纯文本渠道 (PushDeer 等)
    markdown: str  # 飞书卡片 (lark_md)
    level: str = "success"  # success / warning / danger


class FeishuPush:
    """飞书自定义机器人推送"""

    """卡片标题栏配色"""
    LEVEL_COLORS = {
        "success": "green",
        "warning": "orange",
        "danger": "red",
    }

    def __init__(self, webhook: str):
        self.webhook: str = webhook

    def _build_card(self, payload: PushPayload) -> Dict:
        """构建飞书交互式卡片"""
        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": self.LEVEL_COLORS.get(payload.level, "grey"),
                    "title": {"tag": "plain_text", "content": payload.title},
                },
                "elements": [
                    {"tag": "div", "text": {"tag": "lark_md", "content": payload.markdown}},
                    {"tag": "hr"},
                    {
                        "tag": "note",
                        "elements": [{"tag": "plain_text", "content": f"GLaDOS 自动签到 · {beijing_now()}"}],
                    },
                ],
            },
        }

    def send(self, payload: PushPayload) -> bool:
        """发送飞书推送"""
        try:
            response = requests.post(self.webhook, json=self._build_card(payload), timeout=(10, 30))

            data = {}
            try:
                data = response.json()
            except ValueError:
                pass

            # 飞书新旧两种返回格式: code / StatusCode
            code = data.get("code", data.get("StatusCode", -1))

            if response.ok and code == 0:
                logger.info(f"{LogEmoji.PUSH} {LogEmoji.SUCCESS} 飞书推送发送成功。")
                return True

            logger.error(f"{LogEmoji.PUSH} {LogEmoji.ERROR} 飞书推送发送失败: HTTP {response.status_code}, 响应: {response.text}")
            return False
        except Exception as e:
            logger.error(f"{LogEmoji.PUSH} {LogEmoji.ERROR} 发送飞书推送失败: {e}")
            return False


class PushDeerPush:
    """PushDeer 推送"""

    def __init__(self, push_key: str):
        self.push_key: str = push_key

    def send(self, payload: PushPayload) -> bool:
        """发送 PushDeer 推送"""
        try:
            pushdeer = PushDeer(pushkey=self.push_key)
            pushdeer.send_text(payload.title, desp=payload.text)
            logger.info(f"{LogEmoji.PUSH} {LogEmoji.SUCCESS} PushDeer 推送发送成功。")
            return True
        except Exception as e:
            logger.error(f"{LogEmoji.PUSH} {LogEmoji.ERROR} 发送 PushDeer 推送失败: {e}")
            return False


class PushService:
    """推送服务, 支持同时向多个渠道推送"""

    def __init__(self, config: Config):
        self.config = config

    def send(self, payload: PushPayload) -> bool:
        """发送推送, 任一渠道成功即返回 True"""
        channels = []

        if self.config.feishu_webhook:
            channels.append(("飞书", FeishuPush(self.config.feishu_webhook)))
        if self.config.push_key:
            channels.append(("PushDeer", PushDeerPush(self.config.push_key)))

        if not channels:
            logger.info(f"{LogEmoji.WARNING} 未配置任何推送渠道，跳过推送通知。")
            return False

        results = []
        for name, channel in channels:
            logger.info(f"{LogEmoji.PUSH} 正在通过 {name} 推送...")
            results.append(channel.send(payload))

        return any(results)


class Checker:
    """签到"""

    """签到状态对应 Emoji"""
    STATUS_EMOJI = {
        CheckinStatus.SUCCESS: LogEmoji.SUCCESS,
        CheckinStatus.REPEAT: LogEmoji.REPEAT,
        CheckinStatus.FAILURE: LogEmoji.FAIL,
    }

    """兑换状态对应 Emoji"""
    EXCHANGE_EMOJI = {
        ExchangeStatus.SUCCESS: LogEmoji.EXCHANGE,
        ExchangeStatus.FAILURE: LogEmoji.FAIL,
        ExchangeStatus.INSUFFICIENT: LogEmoji.PENDING,
        ExchangeStatus.SKIPPED: "➖",
    }

    def __init__(self, config: Config):
        self.config = config
        self.results: List[CheckinResult] = []

    def _log(self, cookie_idx: int, domain: str, emoji: str, message: str, force: bool = False) -> None:
        """统一日志输出方法"""

        if self.config.verbose or force:
            logger.info(f"{LogEmoji.COOKIE}[{cookie_idx}] {LogEmoji.DOMAIN}[{domain}] {emoji} {message}")

    def checkin_all(self):
        """执行所有签到任务"""
        cookie_count = len(self.config.cookies_list)
        domain_count = len(self.config.domains)
        total_tasks = cookie_count * domain_count
        task_idx = 0

        logger.info(f"{LogEmoji.INFO} 共 {cookie_count} 个 Cookie, {domain_count} 个域名, 共 {total_tasks} 个任务")

        for cookie_idx, cookie in enumerate(self.config.cookies_list, 1):
            logger.info(f"{LogEmoji.START} ========== 开始处理 Cookie {cookie_idx} ==========")

            for domain in self.config.domains:
                task_idx += 1
                logger.info(f"{LogEmoji.INFO} ----- 任务 {task_idx}/{total_tasks}: {LogEmoji.COOKIE}[{cookie_idx}] on {LogEmoji.DOMAIN}[{domain}] -----")

                result = self._checkin_on_domain(cookie, cookie_idx, domain)
                self.results.append(result)

                result_message = f"结果: {result.status}"
                if result.code == CheckinStatus.SUCCESS:
                    if self.config.verbose:
                        result_message = f"结果: {result.status}, 获得 {result.points} 积分, 剩余 {result.days}, 总 {result.points_total}, {result.exchange}"
                    self._log(cookie_idx, domain, LogEmoji.SUCCESS, result_message, force=True)
                else:
                    self._log(cookie_idx, domain, LogEmoji.WARNING, result_message, force=True)

    def _checkin_on_domain(self, cookie: str, cookie_idx: int, domain: str) -> CheckinResult:
        result = CheckinResult(cookie_idx, domain)

        with API(domain, cookie_idx, verbose=self.config.verbose) as api:
            # 1. 获取状态
            self._log(cookie_idx, domain, LogEmoji.STATUS, "查询剩余天数")
            days_str, status_code = api.get_status(cookie)
            result.days = days_str

            # 2. 签到
            self._log(cookie_idx, domain, LogEmoji.CHECKIN, "执行签到")
            checkin_result = api.checkin(cookie)
            result.status = checkin_result["status"]
            result.code = checkin_result.get("code", CheckinStatus.FAILURE)
            result.points = str(checkin_result.get("points", "0"))

            # 3. 获取积分
            self._log(cookie_idx, domain, LogEmoji.POINTS, "查询总积分")
            points_str, points_num = api.get_points(cookie)
            result.points_total = points_str

            # 4. 执行兑换: 仅在积分达标时才调用兑换接口, 避免无意义的失败请求
            required_points = self.config.required_points
            exchange_days = self.config.exchange_days

            if points_str == "None 积分":
                result.exchange = "跳过兑换: 积分查询失败"
                result.exchange_code = ExchangeStatus.SKIPPED
                self._log(cookie_idx, domain, LogEmoji.EXCHANGE, result.exchange, force=True)
            elif points_num < required_points:
                result.exchange = f"积分未达标: {points_num}/{required_points}"
                result.exchange_code = ExchangeStatus.INSUFFICIENT
                self._log(cookie_idx, domain, LogEmoji.PENDING, result.exchange, force=True)
            else:
                self._log(
                    cookie_idx,
                    domain,
                    LogEmoji.EXCHANGE,
                    f"积分已达标 {points_num}/{required_points}, 开始兑换 {self.config.exchange_plan} (+{exchange_days} 天)",
                    force=True,
                )
                result.exchange, result.exchange_code = api.exchange(cookie, self.config.exchange_plan, required_points)

        return result

    def get_results(self) -> List[Dict[str, str]]:
        """获取所有结果"""
        return [result.to_dict() for result in self.results]

    def build_payload(self) -> Tuple[PushPayload, str]:
        """构建推送内容, 同时返回用于日志输出的精简文本"""
        results = self.results

        success_count = sum(1 for r in results if r.code == CheckinStatus.SUCCESS)
        repeat_count = sum(1 for r in results if r.code == CheckinStatus.REPEAT)
        fail_count = sum(1 for r in results if r.code == CheckinStatus.FAILURE)

        ex_success = sum(1 for r in results if r.exchange_code == ExchangeStatus.SUCCESS)
        ex_fail = sum(1 for r in results if r.exchange_code == ExchangeStatus.FAILURE)
        ex_pending = sum(1 for r in results if r.exchange_code == ExchangeStatus.INSUFFICIENT)

        # 签到失败 -> 红色; 仅兑换失败 -> 橙色; 其余 -> 绿色
        if fail_count > 0:
            level = "danger"
            level_emoji = LogEmoji.ERROR
        elif ex_fail > 0:
            level = "warning"
            level_emoji = LogEmoji.WARNING.strip()
        else:
            level = "success"
            level_emoji = LogEmoji.SUCCESS

        title = f"{level_emoji} GLaDOS 签到 {beijing_now('%m-%d')} · 成功{success_count} 重复{repeat_count} 失败{fail_count}"

        plan = self.config.exchange_plan
        summary_lines = [
            f"**{LogEmoji.CHECKIN} 签到**  {LogEmoji.SUCCESS} 成功 {success_count} ｜ {LogEmoji.REPEAT} 重复 {repeat_count} ｜ {LogEmoji.FAIL} 失败 {fail_count}",
            f"**{LogEmoji.EXCHANGE} 兑换**  {LogEmoji.SUCCESS} 成功 {ex_success} ｜ {LogEmoji.PENDING} 未达标 {ex_pending} ｜ {LogEmoji.FAIL} 失败 {ex_fail}",
            f"**{LogEmoji.INFO.strip()} 策略**  {plan} ({self.config.required_points} 积分 → {self.config.exchange_days} 天)",
        ]

        md_lines = ["\n".join(summary_lines), "---"]
        text_lines = []
        log_lines = []

        for i, res in enumerate(results, 1):
            status_emoji = self.STATUS_EMOJI.get(res.code, LogEmoji.FAIL)
            exchange_emoji = self.EXCHANGE_EMOJI.get(res.exchange_code, "➖")

            block = [f"**#{i} · {res.domain}**", f"{status_emoji} {res.status}" + (f" (+{res.points} 积分)" if res.code == CheckinStatus.SUCCESS else "")]

            if res.points_total != "None 积分" or res.days != "None 天":
                block.append(f"{LogEmoji.POINTS} 总积分 **{res.points_total}** ｜ {LogEmoji.PENDING} 剩余 **{res.days}**")

            block.append(f"{exchange_emoji} {res.exchange}")
            md_lines.append("\n".join(block))

            text_lines.append(f"#{i} {res.domain} | {res.status} | +{res.points} | 总{res.points_total} | 剩余{res.days} | {res.exchange}")
            log_lines.append(text_lines[-1] if self.config.verbose else f"#{i} {res.domain} {res.status} | {res.exchange}")

        markdown = "\n".join(md_lines)
        text = "\n".join([line.replace("**", "") for line in summary_lines] + [""] + text_lines)
        log_content = "\n".join(log_lines)

        return PushPayload(title=title, text=text, markdown=markdown, level=level), log_content


# 初始化日志
logger = init_logger()


def main():
    """主函数"""
    config = None
    payload = None

    try:
        # 1. 加载配置
        logger.info(f"{LogEmoji.START} 步骤 1: 加载配置")
        config = Config()

        if not config.cookies_list:
            logger.error(f"{LogEmoji.ERROR} 未找到有效的 Cookie, 退出程序。")
            payload = PushPayload(
                title=f"{LogEmoji.ERROR} GLaDOS 签到 {beijing_now('%m-%d')} · 未找到 Cookie",
                text="未找到有效的 GLADOS_COOKIES, 请检查仓库 Secret 配置。",
                markdown=f"**{LogEmoji.ERROR} 未找到有效的 Cookie**\n请检查仓库 Secret `GLADOS_COOKIES` 是否配置正确。",
                level="danger",
            )
        else:
            # 2. 执行签到
            logger.info(f"{LogEmoji.START} 步骤 2: 执行签到")
            checker = Checker(config)
            checker.checkin_all()

            # 3. 格式化结果
            logger.info(f"{LogEmoji.START} 步骤 3: 格式化结果")
            payload, log_content = checker.build_payload()
            logger.info(f"\n{LogEmoji.END}========== 签到总结 ==========\n{payload.title}\n{log_content}")

    except Exception as e:
        logger.error(f"{LogEmoji.ERROR} 主程序执行过程中发生未预期的错误: {e}")
        payload = PushPayload(
            title=f"{LogEmoji.ERROR} GLaDOS 签到 {beijing_now('%m-%d')} · 脚本执行出错",
            text=f"脚本执行出错: {e}",
            markdown=f"**{LogEmoji.ERROR} 脚本执行出错**\n```\n{e}\n```",
            level="danger",
        )

    # 4. 发送推送
    logger.info(f"{LogEmoji.START} 步骤 4: 发送推送")
    if config is None:
        logger.error(f"{LogEmoji.ERROR} 配置加载失败, 无法发送推送。")
    else:
        PushService(config).send(payload)

    logger.info(f"{LogEmoji.END} 签到完成")


if __name__ == "__main__":
    main()
