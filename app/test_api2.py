import asyncio, httpx, json

async def test_api():
    async with httpx.AsyncClient(base_url='http://localhost:8001') as client:
        r = await client.post('/api/v1/auth/login', json={'email': 'admin@airegistry.local', 'password': 'admin123'})
        token = r.json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}

        # Get graph with detail
        r = await client.get('/api/v1/graph/', headers=headers)
        data = r.json()
        nodes = data.get('nodes', [])
        edges = data.get('edges', [])
        print(f'Graph nodes: {len(nodes)}, edges: {len(edges)}')
        for n in nodes[:5]:
            print(f'  Node: {n}')
        for e in edges[:5]:
            print(f'  Edge: {e}')

        # Get concentration risk
        r = await client.get('/api/v1/graph/concentration-risk', headers=headers)
        print(f'Concentration risk: {r.status_code}')
        if r.status_code == 200:
            for cr in r.json()[:5]:
                print(f'  {cr}')

        # Get portfolio cost
        r = await client.get('/api/v1/portfolio/cost', headers=headers)
        print(f'Portfolio cost: {r.status_code} {r.json() if r.status_code == 200 else r.text[:200]}')

        # Get value summary
        r = await client.get('/api/v1/value/summary', headers=headers)
        print(f'Value summary: {r.status_code}')
        if r.status_code == 200:
            print(f'  {r.json()}')

        # Get waste summary
        r = await client.get('/api/v1/waste/summary', headers=headers)
        print(f'Waste summary: {r.status_code}')
        if r.status_code == 200:
            print(f'  {r.json()}')

        # Get governance overview
        r = await client.get('/api/v1/governance/', headers=headers)
        print(f'Governance overview: {r.status_code}')
        if r.status_code == 200:
            print(f'  {r.json()}')

        # Get users
        r = await client.get('/api/v1/admin/users', headers=headers)
        print(f'Users: {r.status_code}')
        if r.status_code == 200:
            users = r.json()
            for u in users:
                email = u.get('email', '?')
                role = u.get('role', '?')
                print(f'  {email} role={role}')

        # Get taxonomy
        r = await client.get('/api/v1/admin/taxonomy', headers=headers)
        print(f'Taxonomy: {r.status_code}')
        if r.status_code == 200:
            print(f'  {r.json()}')

        # Get top agents by value
        r = await client.get('/api/v1/value/top-agents?limit=5', headers=headers)
        print(f'Top agents: {r.status_code}')
        if r.status_code == 200:
            for a in r.json():
                print(f'  {a.get("name")} value={a.get("valueAmount")}')

        # Get model prices
        r = await client.get('/api/v1/models/prices', headers=headers)
        print(f'Model prices: {r.status_code}')
        if r.status_code == 200:
            for p in r.json():
                print(f'  {p.get("modelName")} input={p.get("inputPrice")}/1M')

asyncio.run(test_api())
