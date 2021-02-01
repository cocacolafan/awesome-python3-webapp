__author__ = "cocla fan"

import asyncio, os, inspect, logging, functools
from urllib import parse
from aiohttp import web
from apis import APIError

def get(path):
    '''
    Define decorator @get('/path)
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'GET'
        wrapper.__route__ = path
        return wrapper
    return decorator

def post(path):
    '''
    Define decorator @post('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper
    return decorator

# 通过inspect库来控制传入的参数：
def get_required_kw_args(fn):    # required_kw_args: 此类参数必须要有传入数值，因为没有默认值。
    args = []
    params = inspect.signature(fn).parameters  # 函数fn的参数类型被放到parameter字典中，{属性名：保存属性的诸如kind、default各种类型的实例}
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)

def get_named_kw_args(fn):      # 此类关键词在调用的时候有没有不是必须的有的会有，有的不会有默认值，搭配上一个函数区分出来，因为有默认值。只是有这个已经named（命名）的参数。
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)

def has_named_kw_args(fn):    # 已命名的关键字参数：判断有没有已经命名的关键字参数，要想给此类关键字传入参数，必须要通过命名(kw=?)才能传入
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True

def has_var_kw_arg(fn):      # 可变关键字参数：**kw类参数，即为可以任意给定的key:value的参数
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True

# 找到有没有关键字key为request的参数，特征是：必须是最后一个POSITIONAL_OR_KEYWORD类型，即已经显示named过，可以通过关键字直接赋值，或者保证在最后一个位置，通过位置赋值
def has_request_arg(fn):
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    for name, param in params.items():
        if name == 'request':
            found = True
            continue
# 1、紧随request后的参数是*args 2、条件1正确，紧挨着request后面的参数不是*args，那么request或者其前面的参数有*args 3、前面两个都不成立，那么request后面的参数必须是**kw
# 即为(arg1, arg2,...argn, request, *args, **kw)或者(arg1, arg2...argn, *args, a, b, ... request, c, ... *kw)或者(arg1, arg2,...argn, request, **kw)
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError("parameter 'request' must be the POSITIONAL_OR_KEYWORD or KEYWORD_ONLY parameter in function: %s%s" % (fn.__name__, str(sig)))
    return found

class RequestHandler(object):

    def __init__(self, app, fn):
        self._app = app
        self._func = fn
        self._has_request_arg = has_request_arg(fn)        # 判断是否是必须要有相关参数传入的函数
        self._has_var_kw_arg = has_var_kw_arg(fn)          # 判断是不是有**kw参数
        self._has_named_kw_args = has_named_kw_args(fn)    # 判断有没有已经显示named过的形参
        self._named_kw_args = get_named_kw_args(fn)        # 找出已经named过的形参并存起来————记为集合A
        self._required_kw_args = get_required_kw_args(fn)  # 找出必须要有相关参数传入的函数————记为集合B   🌂：通过A-B找出带有default值的named_kw_args
    async def __call__(self, request):
        kw = None
        # 如果fn含有**kw类型参数，说明fn可能能够处理request中的某些参数，这时候就全保留这些
        if self._has_var_kw_arg or self._has_named_kw_args:      # 原教程为 if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:
            if request.method == 'POST':
                if not request.content_type:
                    return web.HTTPBadRequest('Missing Content-Type.')
                ct = request.content_type.lower()
                if ct.startswith('application/json'):
                    params = await request.json()
                    if not isinstance(params, dict):   # Requests 中有一个内置的 JSON 解码器，处理 JSON 数据，返回一个字典实例。
                        return web.HTTPBadRequest('JSON body must be object.')
                    kw = params
                elif ct.startswith('application/x-www-form-urlencode') or ct.startswith('multipart/form-data'):
                    params = await request.post()
                    kw = dict(**params)
                else:
                    return web.HTTPBadRequest('Unsupported Content-Type: %s' % request.content_type)
            if request.method == 'GET':
                qs = request.query_string
                if qs:
                    kw = dict()
                    for k, v in parse.parse_qs(qs, True).items():   # 通过parse库解析query_string
                        kw[k] = v[0]
        if kw is None:
            kw = dict(**request.match_info)
        else:
            if not self._has_var_kw_arg and self._named_kw_args:
                #remove all unamedkw: 匹配处理函数fn中有的关键字参数，去掉request里提交上来的，但是fn函数没有的（即没办法处理的）参数
                copy = dict()
                for name in self._named_kw_args:
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            # check named arg:
            for k, v in request.match_info.items():
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s' % k)
                kw[k] = v
        if self._has_request_arg:
            kw['request'] = request
        # check required kw:  required关键字必须传递
        if self._required_kw_args:
            for name in self._required_kw_args:
                if not name in kw:        # if not (name in kw):
                    return web.HTTPBadRequest('Missing argument: %s' % name)
        logging.info('call with args: %s' % str(kw))
        try:
            r = await self._func(**kw)   # 处理好关键参数后，尝试将这些参数传给fn开始处理执行。  🌂此种写法属于将**kw直接传给func()的**kw参数
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)

def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/',path))

def add_route(app, fn):    # 编写add_route函数，用来注册一个URL处理函数：
    method = getattr(fn, '__method__', None)
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s' % str(fn))
    if not asyncio.iscoroutinefunction(fn) and not inspect.isgenerator(fn):   # 如果不是协程或一个generator，将其转化为coroutine
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s(%s)' % (method, path, fn.__name__, ', '.join(inspect.signature(fn).parameters.keys())))
    app.router.add_route(method, path, RequestHandler(app, fn))

# 动态import模块，并扫描模块内部，不用写好几个相同模块的子模块调用语句
def add_routes(app, module_name):
    n = module_name.rfind('.')
    if n == (-1):   # #n=-1,说明module_name中不含'.',动态加载该module
        mod = __import__(module_name, globals(), locals())
    else:
        name = module_name[n+1:]
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)  # 返回name属性的属性值，即为子模块
    for attr in dir(mod):     # dir(a)返回包含a的所有属性、方法名字的list
        if attr.startswith('_'):    # 去除__name__的特殊方法，因为这些方法按约定好的是用不到
            continue
        fn = getattr(mod, attr)     # 返回模块的属性或方法
        if callable(fn):
            method = getattr(fn, '__method__', None)
            path = getattr(fn, '__route__', None)
            if method and path:
                add_route(app, fn)

#    返回'.'最后出现的位置
#    如果为-1，说明是str中不带'.',例如(只是举个例子) handles 、 models
#    如果不为-1,说明str中带'.',例如(只是举个例子) aiohttp.web 、 urlib.parse n分别为 7 和 5
#    __import__()函数性质：由于__import__()不识别. 即为__import__(os)与__import__(os.path)都导入os，而是通过上述参数中加入submoudle名字
#
