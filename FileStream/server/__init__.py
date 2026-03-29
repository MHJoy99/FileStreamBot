from aiohttp import web

def web_server():
    from .stream_routes import routes

    web_app = web.Application(client_max_size=30000000)
    web_app.add_routes(routes)
    return web_app
