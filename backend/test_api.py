import asyncio
import httpx

async def test_api():
    async with httpx.AsyncClient(base_url='http://localhost:8001') as client:
        # Test health
        r = await client.get('/health')
        print(f'Health: {r.status_code} {r.json()}')

        # Test login
        r = await client.post('/api/v1/auth/login', json={'email': 'admin@airegistry.local', 'password': 'admin123'})
        print(f'Login: {r.status_code}')
        if r.status_code == 200:
            data = r.json()
            token = data.get('access_token', '')
            print(f'Token (first 50): {token[:50]}...')

            headers = {'Authorization': f'Bearer {token}'}

            # Get agents
            r = await client.get('/api/v1/agents/?page=1&limit=5', headers=headers)
            print(f'Agents: {r.status_code}')
            if r.status_code == 200:
                data = r.json()
                agents = data.get('data', [])
                pagination = data.get('pagination', {})
                total = pagination.get('total', '?')
                print(f'  Total agents: {total}')
                for a in agents:
                    name = a.get('name', '?')
                    aid = a.get('id', '?')
                    stage = a.get('stage', '?')
                    model = a.get('modelName', '?')
                    print(f'  - {name} ({aid}) stage={stage} model={model}')

            # Run discovery orchestration
            r = await client.post('/api/v1/orchestrations/discovery', headers=headers)
            print(f'Discovery: {r.status_code}')
            if r.status_code == 200:
                print(f'  Result: {r.json()}')
            else:
                print(f'  Error: {r.text[:300]}')

            # Run waste detection
            r = await client.post('/api/v1/orchestrations/waste-detection', headers=headers)
            print(f'Waste Detection: {r.status_code}')
            if r.status_code == 200:
                print(f'  Result: {r.json()}')
            else:
                print(f'  Error: {r.text[:300]}')

            # Run governance workflow
            r = await client.post('/api/v1/orchestrations/governance/inv-recon', headers=headers)
            print(f'Governance: {r.status_code}')
            if r.status_code == 200:
                print(f'  Result: {r.json()}')
            else:
                print(f'  Error: {r.text[:300]}')

            # Run impact analysis
            r = await client.post('/api/v1/orchestrations/impact/inv-recon', headers=headers)
            print(f'Impact Analysis: {r.status_code}')
            if r.status_code == 200:
                print(f'  Result: {r.json()}')
            else:
                print(f'  Error: {r.text[:300]}')

            # Run tokenomics analysis
            r = await client.post('/api/v1/orchestrations/tokenomics/inv-recon', headers=headers)
            print(f'Tokenomics: {r.status_code}')
            if r.status_code == 200:
                print(f'  Result: {r.json()}')
            else:
                print(f'  Error: {r.text[:300]}')

            # Get graph data
            r = await client.get('/api/v1/graph/', headers=headers)
            print(f'Graph: {r.status_code}')
            if r.status_code == 200:
                data = r.json()
                nodes = data.get('nodes', [])
                edges = data.get('edges', [])
                print(f'  Nodes: {len(nodes)}, Edges: {len(edges)}')
            else:
                print(f'  Error: {r.text[:300]}')

            # Get discoveries
            r = await client.get('/api/v1/discoveries/', headers=headers)
            print(f'Discoveries: {r.status_code}')
            if r.status_code == 200:
                data = r.json()
                print(f'  Count: {len(data) if isinstance(data, list) else data}')
            else:
                print(f'  Error: {r.text[:300]}')

        else:
            print(f'Login failed: {r.text[:300]}')

asyncio.run(test_api())
