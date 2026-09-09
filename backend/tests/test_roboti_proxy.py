from dataclasses import replace
from test_aitrol_identity import portal, client
from app.aitrol_identity import membership

TOKEN = 'synthetic-server-token-32-characters'

def setup(portal):
    cfg = replace(portal.state.settings, roboti_proxy_token=TOKEN)
    portal.state.settings = cfg
    # Session factory carries the same settings used by identity().
    portal.state.SessionLocal.configure(info={'settings':cfg})
    return {'X-Roboti-Proxy-Token':TOKEN, 'X-Roboti-User':'synthetic-user-1', 'X-Roboti-Company':'company-a'}

def test_trusted_proxy_has_same_membership_without_cookie(portal, client):
    headers = setup(portal)
    response = client.get('/api/v1/auth/me', headers=headers)
    assert response.status_code == 200
    assert response.json()['user']['company_id'] == 'company-a'
    assert response.json()['user']['role'] == 'auditor'
    assert 'set-cookie' not in response.headers
    assert client.get('/api/v1/auth/me').status_code == 401

def test_bad_secret_revocation_and_company_are_rejected(portal, client):
    headers = setup(portal)
    assert client.get('/api/v1/auth/me', headers={**headers,'X-Roboti-Proxy-Token':'forged'}).status_code == 401
    assert client.get('/api/v1/auth/me', headers={**headers,'X-Roboti-Company':'forbidden'}).status_code == 403
    portal.state.identity_provider.enabled = False
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 403

def test_proxy_mutation_keeps_organization_acl(portal, client):
    headers = setup(portal)
    created = client.post('/api/v1/batches', headers=headers, json={'name':'Synthetic review', 'period':'2026_09','source_mode':'manual','source_system':'dalia'})
    assert created.status_code == 201, created.text
    batch_id = created.json()['id']
    assert client.get('/api/v1/batches/' + batch_id + '/inventory', headers=headers).status_code == 200
    other = {**headers,'X-Roboti-Company':'company-b'}
    assert client.get('/api/v1/batches/' + batch_id + '/inventory', headers=other).status_code == 404

def test_provider_outage_does_not_grant_access(portal, client):
    headers = setup(portal)
    portal.state.identity_provider.available = False
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 503
