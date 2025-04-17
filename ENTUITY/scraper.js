const puppeteer = require('puppeteer');
const fs = require('fs');
const http = require('http');

// Função para obter o horário em Brasília (BRT, UTC-3)
function getBrasiliaTimestamp() {
  const now = new Date();
  const options = {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  };
  const formatter = new Intl.DateTimeFormat('pt-BR', options);
  const [{ value: day }, , { value: month }, , { value: year }, , { value: hour }, , { value: minute }, , { value: second }] = formatter.formatToParts(now);
  return `${year}-${month}-${day} ${hour}:${minute}:${second} BRT`;
}

// Função para criar o servidor de monitoramento na porta 8080
function iniciarServidorMonitoramento() {
  const server = http.createServer((req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('O script está ativo e rodando!\n');
  });

  server.listen(8080, () => {
    console.log('Servidor de monitoramento rodando na porta 8080');
  });
}

// Função para carregar o dados.json
function carregarDados() {
  try {
    const data = fs.readFileSync('dados.json', 'utf8');
    return JSON.parse(data);
  } catch (err) {
    console.error('Erro ao carregar o arquivo dados.json:', err);
    return [];
  }
}

// Carrega o JSON
const dados = carregarDados();

// Função para converter link de systemDeviceSummary para outros dashboards
function converterLink(linkSummary, dashboardType) {
  if (dashboardType === 'systemDeviceResources') {
    return linkSummary
      .replace('dashboardId=systemDeviceSummary', 'dashboardId=systemDeviceResources')
      .replace('dashboardName=Summary', 'dashboardName=Resources');
  } else if (dashboardType === 'systemDevicePorts') {
    return linkSummary
      .replace('dashboardId=systemDeviceSummary', 'dashboardId=systemDevicePorts')
      .replace('dashboardName=Summary', 'dashboardName=Ports');
  }
  return linkSummary;
}

// Função para carregar os resultados existentes do arquivo JSON
function carregarResultados() {
  try {
    const data = fs.readFileSync('resultados.json', 'utf8');
    return JSON.parse(data);
  } catch (err) {
    return [];
  }
}

// Função para salvar os resultados no arquivo JSON
function salvarResultados(resultados) {
  fs.writeFileSync('resultados.json', JSON.stringify(resultados, null, 2));
  console.log('Resultados atualizados e salvos em resultados.json');
}

// Função para aguardar até que os valores reais sejam carregados
async function aguardarValoresReais(iframeContent, seletor) {
  try {
    return await iframeContent.waitForFunction(
      (seletor) => {
        const elementos = document.querySelectorAll(seletor);
        return Array.from(elementos).every(el => el.textContent.trim() !== '--');
      },
      { timeout: 90000 },
      seletor
    );
  } catch (err) {
    console.warn('Erro ao aguardar valores reais:', err);
    return null;
  }
}

// Função para realizar o login
async function realizarLogin(page) {
  try {
    console.log('Tentando realizar login...');
    const loginUrlPattern = /login|signin|auth/i;
    if (loginUrlPattern.test(page.url())) {
      console.log('Página de login detectada:', page.url());
    } else {
      console.log('Não está na página de login, tentando acessar login...');
      await page.goto('https://monitoring.vitait.com/login', {
        waitUntil: 'networkidle2',
        timeout: 60000,
      });
    }

    await page.waitForSelector('input[name="EntUserName"]', { timeout: 60000 });
    await page.type('input[name="EntUserName"]', 'suzano_user');
    await page.type('input[name="EntUserPassword"]', 'Vita@2019');

    await Promise.all([
      page.click('button.wgt.login-button'),
      page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 60000 }).catch(err => {
        console.warn('Navegação após login demorou, continuando...', err);
      }),
    ]);

    const acceptButton = await page.evaluateHandle(() => {
      const buttons = document.querySelectorAll('button');
      for (const btn of buttons) {
        if (btn.textContent.toLowerCase().includes('aceitar') || btn.id.includes('accept') || btn.className.includes('accept')) {
          return btn;
        }
      }
      return null;
    });

    if (acceptButton.asElement()) {
      console.log('Botão de aceitar cookies/termos encontrado, clicando...');
      await acceptButton.click();
      await new Promise(resolve => setTimeout(resolve, 2000));
    } else {
      console.log('Nenhum botão de cookies/termos encontrado.');
    }

    console.log('Login concluído com sucesso.');
    return true;
  } catch (err) {
    console.error('Erro durante o login:', err);
    return false;
  }
}

// Função para processar um link individualmente
async function processarLink(item, resultadosExistentes) {
  let browser;
  try {
    const urlSummary = item.Link;
    console.log(`Acessando URL de systemDeviceSummary: ${urlSummary}`);
    browser = await puppeteer.launch({ headless: true });
    const page = await browser.newPage();

    await page.goto(urlSummary, { waitUntil: 'networkidle2', timeout: 60000 });
    const loginSuccess = await realizarLogin(page);
    if (!loginSuccess) {
      throw new Error('Falha no login');
    }

    if (!page.url().includes('dashboardId=systemDeviceSummary')) {
      console.log('Não está no dashboard Summary esperado, reacessando:', urlSummary);
      await page.goto(urlSummary, { waitUntil: 'networkidle2', timeout: 60000 });
    }

    const errorMessage = await page.evaluate(() => {
      const error = document.querySelector('.error-message, .alert, [class*="error"]');
      return error ? error.textContent.trim() : null;
    });
    if (errorMessage) {
      throw new Error(`Erro no dashboard Summary: ${errorMessage}`);
    }

    await new Promise(resolve => setTimeout(resolve, 30000));
    console.log(`Aguardou 30 segundos para systemDeviceSummary: ${item["Nome SW"]}`);

    // Coleta do systemDeviceSummary
    const iframesSummary = await page.$$('iframe');
    let valoresSummary = Array(4).fill('-');
    let summaryIndex = 0;

    for (let i = 0; i < iframesSummary.length; i++) {
      const iframe = iframesSummary[i];
      const iframeContent = await iframe.contentFrame();
      if (iframeContent) {
        await iframeContent.waitForFunction(() => document.readyState === 'complete', { timeout: 60000 });
        await aguardarValoresReais(iframeContent, '.wgt.number.no-stretch')?.catch(() => {
          console.warn('Valores de Summary não carregaram completamente, continuando...');
        });
        const labels = await iframeContent.$$('.wgt.number.no-stretch');
        for (const label of labels) {
          if (summaryIndex >= 4) break;
          const valor = await iframeContent.evaluate(el => el.textContent.trim(), label);
          if (valor && valor !== '--') {
            valoresSummary[summaryIndex] = valor;
            summaryIndex++;
          }
        }
      }
    }

    console.log(`Valores (%): ${item["Nome SW"]}:`, valoresSummary);

    // Coleta do systemDeviceResources
    const urlResources = converterLink(urlSummary, 'systemDeviceResources');
    console.log(`Acessando URL de systemDeviceResources: ${urlResources}`);
    await page.goto(urlResources, { waitUntil: 'networkidle2', timeout: 60000 });

    if (!page.url().includes('dashboardId=systemDeviceResources')) {
      console.log('Não está no dashboard Resources esperado, reacessando:', urlResources);
      await page.goto(urlResources, { waitUntil: 'networkidle2', timeout: 60000 });
    }

    const errorResources = await page.evaluate(() => {
      const error = document.querySelector('.error-message, .alert, [class*="error"]');
      return error ? error.textContent.trim() : null;
    });
    if (errorResources) {
      throw new Error(`Erro no dashboard Resources: ${errorResources}`);
    }

    await new Promise(resolve => setTimeout(resolve, 15000));
    console.log(`Aguardou 15 segundos para systemDeviceResources: ${item["Nome SW"]}`);

    const iframesResources = await page.$$('iframe');
    let valoresResources = [];

    for (let i = 0; i < iframesResources.length; i++) {
      const iframe = iframesResources[i];
      const iframeContent = await iframe.contentFrame();
      if (iframeContent) {
        await iframeContent.waitForFunction(() => document.readyState === 'complete', { timeout: 60000 });
        const tabelas = await iframeContent.$$('tbody.draggable');
        for (const tabela of tabelas) {
          const linhas = await tabela.$$('tr.selectable-row');
          for (const linha of linhas) {
            const celula = await linha.$('td[data-th="Value"]');
            if (celula) {
              const valor = await iframeContent.evaluate(el => el.textContent.trim(), celula);
              if (valor && valor !== '--') {
                valoresResources.push(valor);
              }
            }
          }
        }
      }
    }

    console.log(`Valores (Sensor): ${item["Nome SW"]}:`, valoresResources);

    // Coleta do systemDevicePorts
    const urlPorts = converterLink(urlSummary, 'systemDevicePorts');
    console.log(`Acessando URL de systemDevicePorts: ${urlPorts}`);
    await page.goto(urlPorts, { waitUntil: 'networkidle2', timeout: 60000 });

    if (!page.url().includes('dashboardId=systemDevicePorts')) {
      console.log('Não está no dashboard Ports esperado, reacessando:', urlPorts);
      await page.goto(urlPorts, { waitUntil: 'networkidle2', timeout: 60000 });
    }

    const errorPorts = await page.evaluate(() => {
      const error = document.querySelector('.error-message, .alert, [class*="error"]');
      return error ? error.textContent.trim() : null;
    });
    if (errorPorts) {
      throw new Error(`Erro no dashboard Ports: ${errorPorts}`);
    }

    await new Promise(resolve => setTimeout(resolve, 15000));
    console.log(`Aguardou 15 segundos para systemDevicePorts: ${item["Nome SW"]}`);

    let portData = [];
    const iframePorts = await page.$('iframe[src*="/webUI/dashlet.do?dashletType=PortListDashlet"]');
    if (iframePorts) {
      const iframeContent = await iframePorts.contentFrame();
      if (iframeContent) {
        await iframeContent.waitForFunction(() => document.readyState === 'complete', { timeout: 60000 });
        await iframeContent.waitForSelector('tbody.table-body', { timeout: 30000 }).catch(() => {
          console.warn('Tabela de portas não carregou, continuando...');
        });

        portData = await iframeContent.evaluate(() => {
          const tableBody = document.querySelector('tbody.table-body');
          if (!tableBody) return [];

          const rowData = [];
          const rows = tableBody.querySelectorAll('tr.selectable-row');
          for (const row of rows) {
            const cells = row.querySelectorAll('td');
            rowData.push({
              Status: cells[0].querySelector('div')?.getAttribute('title') || '',
              VLANs: cells[1].textContent.trim(),
              Port: cells[2].textContent.trim(),
              OutSpeed: cells[3].textContent.trim(),
              InSpeed: cells[4].textContent.trim(),
              FastUtil: cells[5].textContent.trim(),
              FastStatus: cells[6].textContent.trim(),
              StatusEvents: cells[7].textContent.trim(),
              Spare: cells[8].textContent.trim(),
              Duplex: cells[9].textContent.trim(),
              IPs: cells[10].textContent.trim(),
              Hosts: cells[11].textContent.trim(),
            });
          }
          return rowData;
        });
      }
    } else {
      console.log(`Iframe PortListDashlet não encontrado para ${item["Nome SW"]}`);
    }

    console.log(`Dados de Portas: ${item["Nome SW"]}:`, portData);

    // Atualiza ou cria o item nos resultados
    const itemExistente = resultadosExistentes.find(
      existente => existente['Nome SW'] === item['Nome SW'] && existente.IP === item.IP
    );

    const valoresEncontrados = [...valoresSummary, ...valoresResources];
    const timestamp = getBrasiliaTimestamp();

    if (itemExistente) {
      itemExistente.Valores = valoresEncontrados;
      itemExistente.Ports = portData;
      itemExistente.timestamp = timestamp;
      delete itemExistente.Erro;
    } else {
      resultadosExistentes.push({
        'Nome SW': item['Nome SW'],
        IP: item.IP,
        Valores: valoresEncontrados,
        Ports: portData,
        timestamp: timestamp,
      });
    }

    // Calcula a maior temperatura
    const temperaturas = valoresEncontrados.filter(
      v => typeof v === 'string' && v.includes(' C')
    );
    let maiorTemp = '-';
    let maiorValor = -Infinity;
    for (const temp of temperaturas) {
      const valor = parseFloat(temp.split(' ')[0]);
      if (!isNaN(valor) && valor > maiorValor) {
        maiorValor = valor;
        maiorTemp = temp;
      }
    }
    if (itemExistente) {
      itemExistente.temp = maiorTemp;
    } else {
      resultadosExistentes[resultadosExistentes.length - 1].temp = maiorTemp;
    }

    salvarResultados(resultadosExistentes);
  } catch (error) {
    console.error(`Erro ao processar o link para ${item["Nome SW"]}:`, error);
    const itemExistente = resultadosExistentes.find(
      existente => existente['Nome SW'] === item['Nome SW'] && existente.IP === item.IP
    );
    const timestamp = getBrasiliaTimestamp();
    if (itemExistente) {
      itemExistente.Erro = error.message;
      itemExistente.Valores = Array(4).fill('-');
      itemExistente.Ports = [];
      itemExistente.temp = '-';
      itemExistente.timestamp = timestamp;
    } else {
      resultadosExistentes.push({
        'Nome SW': item['Nome SW'],
        IP: item.IP,
        Valores: Array(4).fill('-'),
        Ports: [],
        temp: '-',
        Erro: error.message,
        timestamp: timestamp,
      });
    }
    salvarResultados(resultadosExistentes);
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

// Função para processar os links em lotes de 5
async function processarLotes(dados, resultadosExistentes) {
  const tamanhoLote = 5;
  for (let i = 0; i < dados.length; i += tamanhoLote) {
    const lote = dados.slice(i, i + tamanhoLote);
    await Promise.all(lote.map(item => processarLink(item, resultadosExistentes)));
    console.log(`Lote ${i / tamanhoLote + 1} concluído.`);
  }
}

// Função principal
(async () => {
  iniciarServidorMonitoramento();
  while (true) {
    const resultadosExistentes = carregarResultados();
    await processarLotes(dados, resultadosExistentes);
    console.log('Iteração concluída. Verifique o arquivo resultados.json.');
    await new Promise(resolve => setTimeout(resolve, 60000));
  }
})();