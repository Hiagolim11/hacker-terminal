# Auditoria técnica — versão 0.14.0

Esta revisão cobre o aplicativo GTK/VTE, scripts, metadados e empacotamento. Os testes automatizados estão em `tests/smoke.sh`.

## Problemas encontrados e corrigidos

- **Detecção de fontes custosa:** o aplicativo carregava e verificava todas as famílias instaladas duas vezes. Agora testa primeiro as opções relevantes e interrompe a busca assim que encontra uma Nerd Font completa.
- **Shell em estado inválido:** ações podiam ser enviadas enquanto o shell ainda iniciava ou após seu encerramento. O estado agora é acompanhado explicitamente e a janela fecha quando o shell termina.
- **Inicialização duplicada:** chamadas repetidas podiam tentar abrir mais de um shell no mesmo terminal. Há uma proteção contra spawn concorrente.
- **Cancelamento incompleto:** fechar a janela durante a inicialização deixava a operação assíncrona pendente. O `Gio.Cancellable` agora é cancelado ao destruir o terminal.
- **Tela cheia dessincronizada:** um booleano local podia divergir do estado real da janela. A tecla F11 agora consulta o estado do GDK.
- **Timer retido:** a animação continuava registrada depois da destruição do widget. O callback agora termina junto com a camada de efeitos.
- **Cache de áudio inseguro:** sons eram gravados em caminho previsível sob `/tmp`. Agora usam cache privado do usuário, escrita atômica e diretório temporário seguro como fallback.
- **Falha de áudio derrubava a interface:** erros de escrita ou WAV agora apenas desativam o áudio.
- **Instalação em caminhos com espaços:** a linha `Exec` do desktop entry agora é escapada e citada corretamente.
- **Segunda janela não abria:** a aplicação GTK era registrada como instância única. Agora cada execução cria uma sessão independente.
- **Compatibilidade limitada como terminal:** foram adicionados `-e/--execute` e `--working-directory`; sessões de comando fecham junto com o processo e ocultam ações exclusivas do shell.
- **Comandos relativos com `-e` falhavam:** o spawn agora pesquisa executáveis no `PATH`, permitindo usos como `hacker-terminal -e htop`.
- **Permissão incorreta no pacote:** o changelog compactado agora é normalizado para modo `0644`.
- **Ícone incompleto:** o ícone agora é vetorial, possui identidade hacker e é usado pela janela, menu, instalação local e pacote Debian.
- **Distribuição sem metadados:** foram adicionados AppStream, dependências Debian, scripts de atualização dos caches e validação do conteúdo do pacote.
- **Identidade inconsistente no desktop:** GTK, AppStream e o arquivo `.desktop` agora usam `org.hackerterminal.HackerTerminal`, evitando agrupamento incorreto ou ícone duplicado no dock.
- **Aplicativo monolítico:** a interface, configuração, áudio, efeitos, fontes e terminal foram separados em módulos com responsabilidades claras e testes próprios.
- **Apenas uma sessão por janela:** foram adicionadas abas reordenáveis, títulos dinâmicos, navegação por teclado e confirmação antes de encerrar processos ativos.
- **Histórico difícil de consultar:** cada aba agora possui pesquisa literal com navegação entre resultados e fechamento por `Esc`.
- **Preferências temporárias:** fonte, tamanho, histórico, boot, efeitos, som e painel agora são salvos atomicamente com permissão `0600`.
- **Painel sempre ocupando espaço:** o painel lateral pode ser ocultado pelo cabeçalho e sua escolha é restaurada na próxima execução.
- **Visual fixo no código:** as cores foram movidas para temas INI validados, com cinco opções internas, importação, exportação, aplicação imediata e fallback seguro.
- **Ações desapareciam em janelas baixas:** o painel lateral agora possui rolagem independente e modo compacto acionado pela área disponível.
- **Padrão visual distrativo:** novas configurações usam Minimal Dark sem animação, efeitos ou áudio; o modo hacker completo permanece no perfil Retro Hacker.
- **Fluxos repetitivos:** perfis, ações editáveis e paleta de comandos reduzem navegação e permitem adaptar o terminal ao projeto.
- **Abas perdiam contexto:** novas abas herdam o diretório atual e sessões restauram apenas diretórios locais ainda existentes.
- **Uma tarefa por aba:** cada aba agora pode conter dois painéis, horizontais ou verticais, com foco, fechamento e restauração independentes.
- **Saídas pouco interativas:** URLs validadas são reconhecidas sem interpretar esquemas executáveis e podem ser abertas explicitamente pelo usuário.
- **Contexto do projeto invisível:** branch Git e ambiente virtual são detectados por leitura local e exibidos sem processos auxiliares.
- **Trackpad sem rolagem:** eventos suaves com deltas fracionários agora movimentam o histórico, respeitam seus limites e não interceptam gestos horizontais ou modificados.
- **Processos-filhos ignorados:** a leitura de `/proc` estava após um retorno inalcançável; foi restaurada para proteger tarefas em execução no fechamento.
- **Terminal não reativava após clique externo:** cada clique recebido pelo VTE agora recupera explicitamente o foco e atualiza o painel ativo.
- **Trackpad não reativava o terminal:** VTE e contêiner agora assinam toque, tap, rolagem discreta e suave; toque inicial, liberação sintetizada e rolagem recuperam o foco sem consumir o gesto.
- **Primeiro tap perdido no XFCE/X11:** a janela restaura o foco do painel ativo após ser reativada, cobrindo o evento consumido pelo gerenciador de janelas.
- **Rolagem suave interceptada cedo demais:** o código manual foi removido; o VTE agora usa fallback nativo e unidades em pixels, a configuração prevista para `GtkScrolledWindow` e deltas XInput/libinput.
- **Sessões acima do limite:** a gravação podia persistir até 40 painéis apesar do limite de 20 na leitura; ambos os sentidos agora aplicam o mesmo teto.

- **Preferências quase vazias:** a área rolável era adicionada ao diálogo sem expansão e recebia cerca de 42 px; só a primeira opção aparecia. Os quatro diálogos agora expandem o conteúdo, com teste de regressão.
- **Terminal espremido em janelas estreitas:** o `Gtk.Paned` reposicionado a cada `configure-event` podia entregar quase toda a largura ao painel lateral. O painel agora fica em um contêiner de largura fixa e é ocultado automaticamente abaixo de 760 px.
- **Timer de efeitos sempre ativo:** cada painel acordava a cada 75 ms mesmo com efeitos desligados; o timer agora só existe enquanto os efeitos estão ligados.

- **Preferências apagadas por `%`:** o `configparser` usava interpolação; um `%` em fonte ou shell fazia a leitura cair nos padrões e a gravação lançar exceção. A interpolação foi desativada e há teste de regressão.
- **Seções extras descartadas:** salvar reescrevia o arquivo inteiro; agora as seções não gerenciadas são mantidas.
- **Colagem perigosa:** textos com quebras de linha ou sequências de controle eram enviados sem aviso; agora pedem confirmação (configurável).
- **Erros invisíveis:** exceções em callbacks GTK só apareciam no stderr; agora ficam em log rotativo com permissão `0600`.
- **Layout perdido em falhas:** a sessão só era salva ao fechar normalmente; agora há gravação automática periódica.
- **Shell inválido sem saída:** um shell personalizado inexistente deixava a aba inutilizável; agora há fallback automático para o shell de login.

- **Touchpad sem rolagem com efeitos ligados:** a chuva digital e as scanlines ficavam num filho de `Gtk.Overlay`, cuja janela GDK recebia a rolagem do X11 apesar de `set_overlay_pass_through`; o VTE não recebia nenhum evento. Os testes anteriores entregavam eventos sintéticos direto ao VTE e não cobriam o hit-test do X. Os efeitos passaram a ser desenhados após o VTE, e o teste agora usa eventos reais.

- **Som do teclado mudo após poucas teclas (0.12.0):** cada voz `appsrc → pulsesink` recebia buffers esparsos; após o primeiro esvaziamento, a stream não tocava mais, com ou sem timestamps ou flush. Os testes usavam `fakesink` e um som por voz, e não detectaram. A saída virou uma stream contínua com mixer próprio; a correção foi validada gravando o monitor de um sink nulo do PipeWire durante digitação simulada.

- **Visualizador sem custo quando não usado:** o módulo de interface do visualizador só é importado no primeiro arquivo aberto, e cliques comuns no terminal não fazem busca de links ou arquivos.
- **Leitura de planilhas limitada:** a primeira versão lia o CSV inteiro em memória (8,7 s e 358 MB de pico para 300 mil linhas, segurando o GIL). Agora é em fluxo (~0,1 s e 9 MB); XLSX usa a dimensão declarada e há um orçamento de linhas percorridas para XLSX sem dimensão e ODS.
- **PATH redefinido pelo shell de login:** o `/etc/profile` do Kali reescreve o `PATH`, então o `ht-open` é instalado em um diretório padrão em vez de depender do ambiente herdado.
- **Socket UNIX:** caminho limitado a 108 bytes com alternativa automática, diretórios inseguros ignorados e sockets de processos encerrados removidos.

- **Padding do terminal ignorado:** o VTE registra seu próprio CSS (padding de 1 px) com prioridade de aplicação, empatando com o do app e vencendo; o recuo do tema nunca tinha efeito. O CSS do app usa agora prioridade 601. Com a curvatura dos temas CRT isso cortava a primeira letra; o raio do canto é limitado a 3× o recuo, o que mantém o texto sempre visível (há teste para isso).
- **Custo dos efeitos CRT:** brilho, vinheta e curvatura são renderizados uma vez em superfícies em cache; a cada quadro só há cópias e o ruído usa texturas fixas. Medido ~3% de CPU parado, abaixo da chuva digital (~7%).

## Verificações

- compilação Python e argumentos da CLI;
- sintaxe de todos os scripts Bash;
- parsing do CSS pelo GTK;
- XML do SVG e AppStream;
- desktop entry da instalação local e do pacote;
- renderização do SVG em 256×256 quando ImageMagick está disponível;
- instalação e remoção em caminhos contendo espaços;
- construção, inspeção, extração e execução do conteúdo do `.deb`;
- diagnóstico de GTK, VTE, shell, Powerline e Nerd Font.
- testes unitários de configuração, limites, variáveis de ambiente, parser, shell, áudio e inspeção de processos;
- smoke test GTK/VTE real sob Xvfb para abas, busca, títulos, preferências, painel e fechamento de sessão;
- execução com avisos GTK convertidos em erros para detectar problemas silenciosos de interface.
- redimensionamento real de 1180×720 para 800×500, verificando as oito ações, rolagem lateral e modo compacto;
- parsing das cinco paletas internas, rejeição de temas corrompidos, override do usuário e cópia atômica com permissão `0600`.
- round-trip e permissões de ações e sessões, fallback de arquivos corrompidos, perfis completos e URI de diretório;
- restauração gráfica de duas abas e busca/execução real pela paleta de comandos.
- divisão horizontal e vertical, fechamento do painel ativo e restauração da orientação;
- normalização de links e detecção de Git/virtualenv em diretórios aninhados.
- rolagem suave positiva e negativa, saturação nos dois limites e evento real no widget GTK/VTE;
- detecção de um processo-filho real durante sua execução.
- alternância de foco do painel lateral para o terminal e sincronização do painel ativo.
- toque nativo, tap sintetizado, máscara de eventos e foco recuperado durante rolagem suave.
- propriedades nativas `enable-fallback-scrolling` e `scroll-unit-is-pixels` do VTE;
- perda e recuperação de foco no nível da janela, simulando o comportamento do XFCE/X11;
- serialização e leitura de sessões no limite exato de 20 painéis;
- análise estática Pylint sem novos erros de lógica no código do aplicativo.

Ferramentas gráficas e combinações específicas de gerenciadores de janela ainda devem ser testadas manualmente em diferentes desktops Linux antes de cada release pública.
