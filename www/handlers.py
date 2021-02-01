import re, time, json, logging, hashlib, base64, asyncio
from models import User, Comment, Blog, next_id
from coroweb import get, post

@get('/')
async def index(request):
    users = await User.findAll()
    return{
        '__template__': 'test.html',
        'users': users
    }
