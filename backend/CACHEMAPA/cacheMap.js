const express = require('express');
const axios = require('axios');
const NodeCache = require('node-cache');
const https = require('https');
const app = express();
const port = 3000;

const tileCache = new NodeCache({ stdTTL: 24 * 60 * 60, checkperiod: 120 });

const axiosInstance = axios.create({
    httpsAgent: new https.Agent({ rejectUnauthorized: false })
});

app.use((req, res, next) => {
    res.header('Access-Control-Allow-Origin', '*');
    res.header('Access-Control-Allow-Methods', 'GET');
    next();
});

// Função para pré-carregar tiles em um raio de 50 km para um nível de zoom específico
async function preloadTiles(lat, lng, zoom) {
    const tilesPerDegree = Math.pow(2, zoom) / 360;
    const latDegreePerKm = 1 / 111;
    const radiusDegrees = 10 * latDegreePerKm;
    const lngDegreePerKm = latDegreePerKm * Math.cos(lat * Math.PI / 180);

    const minLat = lat - radiusDegrees;
    const maxLat = lat + radiusDegrees;
    const minLng = lng - (10 * lngDegreePerKm);
    const maxLng = lng + (10 * lngDegreePerKm);

    const minX = Math.floor((minLng + 180) / 360 * Math.pow(2, zoom));
    const maxX = Math.floor((maxLng + 180) / 360 * Math.pow(2, zoom));
    const minY = Math.floor((1 - Math.log(Math.tan(maxLat * Math.PI / 180) + 1 / Math.cos(maxLat * Math.PI / 180)) / Math.PI) / 2 * Math.pow(2, zoom));
    const maxY = Math.floor((1 - Math.log(Math.tan(minLat * Math.PI / 180) + 1 / Math.cos(minLat * Math.PI / 180)) / Math.PI) / 2 * Math.pow(2, zoom));

    for (let x = minX; x <= maxX; x++) {
        for (let y = minY; y <= maxY; y++) {
            const tileUrl = `https://a.basemaps.cartocdn.com/dark_all/${zoom}/${x}/${y}.png`;
            const cacheKey = `dark-${zoom}-${x}-${y}`;
            if (!tileCache.get(cacheKey)) {
                try {
                    const response = await axiosInstance.get(tileUrl, { responseType: 'arraybuffer', timeout: 5000 });
                    const tileData = Buffer.from(response.data, 'binary');
                    tileCache.set(cacheKey, tileData);
                } catch (error) {
                    console.error(`Erro ao pré-carregar tile ${tileUrl}:`, error.message);
                }
            }
        }
    }
}

// Função para pré-carregar todos os hosts em múltiplos zooms
async function preloadAllHosts() {
    let hosts;
    try {
        const response = await axios.get('http://172.16.196.36:5000/status', {
            headers: {
                'Authorization': 'Bearer SEU_TOKEN_AQUI' // Adicione o token correto aqui, se necessário
            }
        });
        hosts = response.data.hosts;
    } catch (error) {
        console.error('Erro ao buscar hosts:', error.response?.data || error.message);
        // Fallback para hosts estáticos
        hosts = [
            { nome: 'Imperatriz', local: '-5.5264, -47.4917' },
            { nome: 'Belém', local: '-1.4558, -48.4902' },
            { nome: 'Aracruz', local: '-19.8204, -40.2733' }
        ];
        console.log('Usando hosts estáticos como fallback');
    }

    for (const host of hosts) {
        if (host.local && host.nome) {
            const [lat, lng] = host.local.split(', ').map(Number);
            console.log(`Iniciando pré-carregamento para o host: ${host.nome}`);
            for (let zoom = 14; zoom <= 18; zoom++) {
                await preloadTiles(lat, lng, zoom);
            }
            console.log(`Todos os tiles do host ${host.nome} armazenados no cache`);
        } else {
            console.warn(`Host sem nome ou localização: ${JSON.stringify(host)}`);
        }
    }
    console.log('Pré-carregamento de todos os hosts concluído');
}

app.get('/tiles/:type/:z/:x/:y', async (req, res) => {
    const { type, z, x, y } = req.params;
    const cacheKey = `${type}-${z}-${x}-${y}`;
    
    const cachedTile = tileCache.get(cacheKey);
    if (cachedTile) {
        console.log(`Tile ${cacheKey} servido do cache`);
        res.set('Content-Type', 'image/png');
        return res.send(cachedTile);
    }

    let tileUrl;
    switch (type) {
        case 'dark': tileUrl = `https://a.basemaps.cartocdn.com/dark_all/${z}/${x}/${y}.png`; break;
        case 'light': tileUrl = `https://a.basemaps.cartocdn.com/light_all/${z}/${x}/${y}.png`; break;
        case 'satellite': tileUrl = `https://mt1.google.com/vt/lyrs=s&x=${x}&y=${y}&z=${z}`; break;
        default: 
            console.log(`Tipo de tile inválido: ${type}`);
            return res.status(400).send('Tipo de tile inválido');
    }

    console.log(`Buscando tile: ${tileUrl}`);
    try {
        const response = await axiosInstance.get(tileUrl, { responseType: 'arraybuffer', timeout: 5000 });
        const tileData = Buffer.from(response.data, 'binary');
        tileCache.set(cacheKey, tileData);
        console.log(`Tile ${cacheKey} armazenado no cache`);
        res.set('Content-Type', 'image/png');
        res.send(tileData);
    } catch (error) {
        console.error(`Erro ao buscar tile ${tileUrl}:`, error.message);
        res.status(500).send(`Erro ao carregar tile: ${error.message}`);
    }
});

app.listen(port, () => {
    console.log(`Servidor rodando em http://172.16.196.36:${port}`);
    // Inicia o pré-carregamento em segundo plano
    preloadAllHosts().catch(err => console.error('Erro no pré-carregamento:', err));
});