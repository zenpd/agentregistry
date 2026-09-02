import asyncio, httpx

async def test():
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post('http://localhost:8001/api/v1/auth/login', json={'email':'admin@airegistry.local','password':'admin123'})
        print(f'Login: {r.status_code}')
        token = r.json()['access_token']
        h = {'Authorization': f'Bearer {token}'}

        r = await c.get('http://localhost:8001/api/v1/value/summary', headers=h)
        print(f'Value summary: {r.status_code}')
        print(f'  Body: {r.text[:500]}')

        r = await c.get('http://localhost:8001/api/v1/waste/summary', headers=h)
        print(f'Waste summary: {r.status_code}')
        print(f'  Body: {r.text[:500]}')

        r = await c.get('http://localhost:8001/api/v1/agents/?page=1&limit=2', headers=h)
        print(f'Agents: {r.status_code}')
        if r.status_code == 200:
            for a in r.json()['data']:
                name = a.get('name', '?')
                dept = a.get('dept', 'N/A')
                keys = list(a.keys())
                print(f'  {name} dept={dept} keys={keys}')
        else:
            print(f'  Body: {r.text[:200]}')

asyncio.run(test())
