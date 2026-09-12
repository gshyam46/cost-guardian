"""Role startup and cooperative signal shutdown for the packaged deployment."""
import asyncio
import logging
import signal

from .errors import DeploymentError

logger = logging.getLogger(__name__)
SHUTDOWN_SECONDS = 45


def database(configuration):
    from motor.motor_asyncio import AsyncIOMotorClient
    try:
        client = AsyncIOMotorClient(configuration.mongo_url, serverSelectionTimeoutMS=3000,
            connectTimeoutMS=2000, socketTimeoutMS=10000, appname="guardian-deployment")
        return client, client[configuration.database_name]
    except Exception:
        raise DeploymentError("database_unavailable") from None


async def supervised(operation, cleanup, *, stop=None, shutdown_seconds=SHUTDOWN_SECONDS):
    """Cancel the selected loop and close resources without acknowledging work."""
    loop = asyncio.get_running_loop()
    supplied_stop = stop is not None
    stop = stop or asyncio.Event()
    previous = {}
    if not supplied_stop:
        for number in (signal.SIGINT, signal.SIGTERM):
            previous[number] = signal.getsignal(number)
            try:
                loop.add_signal_handler(number, stop.set)
            except NotImplementedError:
                signal.signal(number, lambda *_: loop.call_soon_threadsafe(stop.set))
    task = asyncio.create_task(operation())
    waiter = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
            return
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=shutdown_seconds)
        if task not in done:
            raise DeploymentError("shutdown_timed_out")
        try:
            await task
        except asyncio.CancelledError:
            pass
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        if not task.done():
            task.cancel()
        try:
            async with asyncio.timeout(5):
                await cleanup()
        finally:
            for number, handler in previous.items():
                try:
                    loop.remove_signal_handler(number)
                except NotImplementedError:
                    pass
                signal.signal(number, handler)


async def worker_loop(db, configuration, role):
    if role == "notifications":
        from notifications.settings import load_notification_settings
        from notifications.worker import process_once
        notification = load_notification_settings(configuration.identity)
        if notification.state != "configured":
            raise DeploymentError("notifications_not_configured")
    else:
        from guardian.direct_worker import poll_direct_once
    while True:
        try:
            if role == "notifications":
                await process_once(db, configuration.identity, notification)
            else:
                await poll_direct_once(db, configuration.identity)
        except Exception:
            logger.warning("Guardian worker pass blocked; durable work remains pending")
        await asyncio.sleep(1 if role == "notifications" else configuration.poll_interval)


async def run_role(configuration, role):
    from .readiness import ready
    client, db = database(configuration)
    if role not in {"api", "worker", "notifications"}:
        client.close()
        raise DeploymentError("invalid_role")
    try:
        if not await ready(db, configuration):
            raise DeploymentError("deployment_not_ready")
        if role == "api":
            client.close()
            import uvicorn
            from server import app
            app.state.deployment_configuration = configuration
            server = uvicorn.Server(uvicorn.Config(app, host=configuration.bind_host, port=configuration.port,
                proxy_headers=bool(configuration.trusted_proxy_ips),
                forwarded_allow_ips=",".join(configuration.trusted_proxy_ips),
                timeout_graceful_shutdown=45, log_level="info"))
            await server.serve()
        else:
            async def close():
                client.close()
            await supervised(lambda: worker_loop(db, configuration, role), close)
    finally:
        client.close()
