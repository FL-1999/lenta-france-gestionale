"""Stateless Streamable HTTP MCP: JSON responses; no server push is needed."""
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session
from database import get_db
from services.assistant_security import settings, rate_limit
from services.assistant_oauth import MCP, access_owner
from services.assistant_mcp import catalogue, INSTRUCTIONS
from audit_utils import log_audit_event

router = APIRouter(include_in_schema=False)
VERSION = '2025-06-18'


def rpc_error(ident, code, message):
    return JSONResponse({'jsonrpc': '2.0', 'id': ident, 'error': {'code': code, 'message': message}})


def authenticate(request, db, scope):
    header = request.headers.get('authorization', '')
    scheme, _, token = header.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise HTTPException(401, 'Collega il tuo account Lenta', headers={
            'WWW-Authenticate': f'Bearer resource_metadata="{settings().origin}/.well-known/oauth-protected-resource{MCP}"'})
    return access_owner(db, token, scope)


@router.api_route(MCP, methods=['GET', 'DELETE'])
def no_stream(request: Request, db: Session = Depends(get_db)):
    if request.headers.get('origin', settings().origin) != settings().origin:
        raise HTTPException(403, 'Origine non autorizzata')
    authenticate(request, db, None)
    return Response(status_code=405, headers={'Allow': 'POST'})


@router.post(MCP)
async def mcp(request: Request, db: Session = Depends(get_db)):
    origin = request.headers.get('origin')
    if origin and origin != settings().origin:
        raise HTTPException(403, 'Origine non autorizzata')
    version = request.headers.get('mcp-protocol-version')
    if version and version not in (VERSION, '2025-03-26'):
        raise HTTPException(400, 'Versione MCP non supportata')
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        raise HTTPException(415, 'Richiesto application/json')
    try:
        body = await request.json()
    except (ValueError, UnicodeError):
        return rpc_error(None, -32700, 'JSON non valido')
    if (not isinstance(body, dict) or body.get('jsonrpc') != '2.0'
            or not isinstance(body.get('method'), str)
            or ('id' in body and (isinstance(body['id'], bool) or not isinstance(body['id'], (str, int))))):
        return rpc_error(None, -32600, 'Richiesta JSON-RPC non valida')
    ident, method, params = body.get('id'), body['method'], body.get('params', {})
    if not isinstance(params, dict):
        return rpc_error(ident, -32602, 'Parametri non validi')
    # Handshake and tool descriptions contain no user data. Every tool requires OAuth.
    public = method in ('initialize', 'notifications/initialized', 'tools/list', 'ping')
    if request.headers.get('authorization') or not public:
        authenticate(request, db, None)
    if 'id' not in body:
        return Response(status_code=202)
    if method == 'initialize':
        result = {'protocolVersion': VERSION, 'serverInfo': {'name': 'Lenta personale', 'version': '1.0.0'},
            'capabilities': {'tools': {'listChanged': False}}, 'instructions': INSTRUCTIONS}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': [tool.metadata() for tool in catalogue().values()]}
    elif method == 'tools/call':
        name = params.get('name')
        tool = catalogue().get(name) if isinstance(name, str) else None
        if not tool:
            return rpc_error(ident, -32602, 'Strumento sconosciuto')
        user = authenticate(request, db, tool.scope)
        rate_limit(db, user.id, not tool.read_only)
        try:
            values = tool.schema.model_validate(params.get('arguments', {}))
            data = jsonable_encoder(tool.invoke(values, db, user))
            result = {'content': [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False)}],
                      'structuredContent': data, 'isError': False}
        except ValidationError as exc:
            db.rollback()
            result = {'content': [{'type': 'text', 'text': json.dumps(exc.errors(include_input=False, include_url=False), default=str)}], 'isError': True}
        except HTTPException as exc:
            db.rollback()
            result = {'content': [{'type': 'text', 'text': json.dumps({'status': exc.status_code, 'detail': exc.detail}, ensure_ascii=False)}], 'isError': True}
        log_audit_event(db, user, 'assistant.mcp.call', 'integration', extra_data={'tool': name, 'error': result['isError']})
        db.commit()
    else:
        return rpc_error(ident, -32601, 'Metodo non disponibile')
    return JSONResponse({'jsonrpc': '2.0', 'id': ident, 'result': result})
