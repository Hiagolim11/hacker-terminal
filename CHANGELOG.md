# Changelog

Este projeto segue [Semantic Versioning](https://semver.org/).

## 0.16.1

- Corrige o erro “identificador inválido” ao criar uma conexão SSH em **Nova…**: o identificador interno passa a ser gerado a partir do nome antes da validação. Um teste cobre agora a criação e a edição pelo gerenciador.

## 0.16.0

- **Integração com o shell** (zsh e bash, automática): cada prompt é marcado. `Ctrl+Shift+↑/↓` pula entre comandos, `Ctrl+Shift+L` copia a saída do último comando, uma faixa na margem fica vermelha nos comandos que falharam, a barra de status mostra o código de saída e o aviso de comando longo diz se ele deu certo. Seus arquivos `.zshrc`/`.bashrc` continuam sendo carregados normalmente; desligue em *Preferências → Geral*. Requer VTE 0.78 ou mais novo (`--diagnose` informa); em versões antigas o terminal funciona como antes.
- **Digitar em todos os painéis da aba** (`Ctrl+Shift+I` ou botão direito): o que você digita vai para todos os painéis; a moldura fica vermelha enquanto transmite.
- **Gerenciador de conexões SSH** (`Ctrl+Shift+S`, botão na barra ou paleta): conexões salvas e hosts do `~/.ssh/config`, cada uma com tema próprio (novo tema **Alerta Vermelho** para produção) e confirmação opcional antes de conectar. Senhas nunca são guardadas; destinos e opções são validados contra injeção de opções.
- **Comandos com campos** nas ações rápidas: `nmap -sV {alvo}` ou `ping -c {vezes=4} {host}` pedem os valores num formulário com prévia antes de rodar. Os valores são protegidos com aspas e nunca executam como código.
- **Terminal suspenso estilo Quake**: `hacker-terminal --dropdown` abre e esconde um terminal no topo da tela. Em *Preferências → Geral* um status mostra se o atalho está ativo (✓), ainda não ativo (○) ou se a tecla já é usada por outro programa (⚠), com botões **Ativar atalho**, **Desativar** e **Testar agora**; no XFCE o F12 é sugerido e teclas de outros programas nunca são substituídas. Ele se reposiciona quando a resolução ou os monitores mudam e aplica uma nova altura na hora. Também há a ação “Terminal suspenso” no menu de aplicativos.
- **Tamanho das divisões e nomes dos painéis** são lembrados na sessão. `Ctrl+Shift+R` (ou botão direito) dá um nome a um painel, mostrado numa faixa no topo dele, na aba e nos avisos.
- Novos temas **Papel (claro)** e **Alto Contraste**, com contraste verificado (WCAG AA e AAA). Menus e diálogos seguem o tema claro ou escuro.
- A integração informa a pasta atual ao terminal (OSC 7), e novas abas e divisões abrem na pasta onde você está. Antes, a pasta enviada pelo shell era descartada quando vinha com o nome da máquina; uma pasta de outra máquina (sessão SSH) continua sendo ignorada.
- A faixa de boas-vindas é exibida antes do shell iniciar e não se mistura mais com o prompt.
- Funciona em VTE sem termprops (por exemplo, Ubuntu 24.04), com a integração desligada.

## 0.15.0

- **Até 4 painéis por aba**: as divisões agora se aninham (por exemplo, uma grade 2×2) e, ao fechar um painel, o vizinho ocupa o espaço. `Ctrl+Shift+O` percorre os painéis na ordem visual.
- A sessão (formato 3) guarda a árvore de divisões completa, valida o arquivo ao carregar (dados adulterados ou pastas apagadas voltam com segurança para um painel) e continua lendo sessões das versões anteriores.
- **Aviso de comando longo**: quando um comando que durou mais que o limite (10 s por padrão) termina numa aba que você não está olhando, a aba fica marcada e uma notificação do sistema aparece; clicar nela abre a aba certa. Funciona com qualquer shell, sem configuração (o terminal observa o processo em execução em `/proc`, uma vez por segundo, apenas com o recurso ligado).
- **Salvar a saída** do terminal (todo o histórico) e **gravar a saída** continuamente em `.txt` ou `.html` com as cores do tema, pelo menu do botão direito ou pela paleta. Durante a gravação o histórico daquele painel fica ilimitado e as linhas são gravadas a cada segundo e antes de cada comando, para que nada se perca em saídas rápidas; a aba e a barra de status indicam a gravação.
- Mensagens rápidas na barra de status (por exemplo, "1500 linhas salvas em ~/…") em vez de diálogos.
- Corrige a remoção de timers já descartados pelo GLib ao fechar a janela, que podia gerar avisos.

## 0.14.0

- Oito temas **Fósforo**, inspirados no Cool Retro Term: Fósforo Âmbar, Fósforo Verde, Fósforo Verde Scanlines, Fósforo Vintage, Micro 1977, Mainframe 3270, DOS VGA e Fósforo Futurista.
- Visual de monitor CRT com os efeitos visuais ligados: brilho do fósforo, vinheta, ruído estático, cintilação, curvatura do tubo com cantos arredondados, sombra interna e reflexo, além de scanlines.
- Paletas monocromáticas como num tubo real (todas as cores ANSI no mesmo tom, variando só o brilho) e seleção em vídeo inverso; o DOS VGA usa a paleta de 16 cores do VGA.
- Novo perfil **Retrô CRT**, que aplica o Fósforo Âmbar com efeitos, animação de abertura e sem painel lateral.
- Os temas podem sugerir uma fonte: as Preferências mostram a sugestão, o pacote a instalar e um botão **Usar** quando ela já está instalada.
- O editor de temas ganhou controles para brilho, vinheta, ruído, cintilação, curvatura, chuva digital e fonte sugerida; o formato `.ini` aceita essas chaves opcionais em `[effects]` e `font` em `[theme]`.
- Leve: as camadas estáticas são desenhadas uma vez por tamanho e tema e reaproveitadas; o ruído usa texturas pré-geradas; um tema sem partes animadas não mantém timer. Medido: ~3% de CPU parado com os efeitos CRT, contra ~7% da chuva digital, e 0% com efeitos desligados.
- Corrige o recuo interno do terminal: o padding definido pelo tema nunca era aplicado, porque o VTE instala o próprio CSS com a mesma prioridade; o CSS do app passa a usar prioridade de aplicação + 1 (o `gtk.css` do usuário continua prevalecendo).

## 0.13.0

- Visualizador de imagens e planilhas em abas, ao lado do terminal de origem: `ht-open ARQUIVO`, `Ctrl+clique` em nomes de arquivo na saída (por exemplo, de um `ls`), menu do botão direito ou a paleta de comandos.
- Imagens: PNG, JPEG, GIF animado, WebP, SVG, AVIF, TIFF, BMP e outros formatos do GdkPixbuf, com ajuste à janela, zoom (`+`, `-`, `0`, `F`, `Ctrl` + roda) e orientação EXIF.
- Planilhas: CSV/TSV (delimitador e codificação detectados), XLSX e ODS, com várias planilhas, colunas no estilo A, B, C, datas e horas formatadas, fórmulas e cópia das linhas selecionadas como texto tabulado.
- Leve por construção: o visualizador só é carregado no primeiro uso; leitura em segundo plano e tabela preenchida em blocos; até 5.000 linhas × 200 colunas exibidas, com total exato, estimado (≈) ou mínimo (mais de) para arquivos maiores. Um CSV de 300 mil linhas abre em ~0,1 s.
- Seguro: o `ht-open` fala com o terminal por um socket UNIX privado (0600, em diretório 0700 verificado) e só pode pedir visualização; arquivos zip corrompidos ou grandes demais são recusados com uma mensagem clara.
- `install.sh` e o pacote `.deb` instalam o comando `ht-open` (sem sobrescrever um comando de mesmo nome do usuário).
- O terminal agora encerra de forma limpa com SIGTERM/SIGINT, salvando a sessão e liberando socket e áudio.
- Corrige um teste intermitente do som (~7% das execuções): o `fakesink` de teste podia ficar preso entre PAUSED e PLAYING após a pausa por inatividade. O `pulsesink` real não tem esse problema (180 de 180 retomadas com som em ~5 ms).

## 0.12.2

- README reescrito: instalação passo a passo, guia de personalização, referência completa de configuração e linha de comando, arquitetura, motor de som, segurança e solução de problemas.
- Capturas de tela dos cinco temas, dos painéis, da paleta e das preferências, e amostras de áudio dos switches em `docs/`.
- O pacote `.deb` passa a recomendar `gstreamer1.0-plugins-base` e `gstreamer1.0-plugins-good`, necessários para o som do teclado.
- O CI instala o GStreamer para executar os testes de som.
- O pacote passa a depender de `python3-gi-cairo` e a recomendar `librsvg2-common`: sem eles, um sistema limpo registrava erros a cada quadro desenhado e não carregava ícones SVG. Os efeitos visuais só se conectam ao desenho do terminal quando estão ligados e são desativados com aviso se o suporte a cairo faltar.
- Corrige um travamento intermitente (segfault) ao encerrar: o fluxo de áudio continuava chamando código Python durante a finalização do interpretador. O mixer agora para no encerramento do aplicativo e via `atexit`, e os blocos de áudio usam memória do próprio GStreamer.

## 0.12.1

- Corrige o som do teclado, que parava depois das primeiras teclas: cada uma das 8 streams de áudio tocava uma única vez, porque o PulseAudio/PipeWire não retoma uma stream alimentada por buffers esparsos depois do primeiro esvaziamento.
- O áudio agora é uma única stream contínua alimentada em blocos de 5 ms; cada tecla é mixada no próximo bloco, com sobreposição e limitação de pico seguras.
- Latência medida no PipeWire: ~7 ms até o bloco com o som e ~11 ms do dispositivo, ~18 ms no total (a estimativa de 10–15 ms da 0.12.0 era otimista).
- Testes passam a verificar o conteúdo dos blocos que chegam ao sink em várias teclas separadas por silêncio e após a pausa por inatividade.

## 0.12.0

- Som de teclado mecânico: switches Linear (estilo Red), Tátil (estilo Brown) e Clicky (estilo Blue), sintetizados a partir dos eventos físicos de cada switch: clique da jaqueta, bump tátil, fundo do curso, retorno da haste e estabilizadores.
- Sons distintos para a descida e a subida da tecla e timbre mais grave para espaço, Enter, Backspace, Shift e Tab; cada tecla tem variações próprias.
- Segurar uma tecla não repete o som, como num teclado real.
- Pacotes gravados: importe pacotes Mechvibes (`config.json`, tipos *single* e *multi*) ou pastas com `press*.wav`/`release*.wav` para o som exato de um teclado real.
- Nova aba **Preferências → Som do teclado** com switch, volume, som ao soltar, campo de teste com prévia ao vivo e importação de pacotes.
- Motor de baixa latência com PCM pré-decodificado em memória e ~0,1 ms por tecla no programa. Remove a trava de 65 ms e o reinício de pipeline a cada tecla, que causavam o atraso.
- As vozes pausam após 15 s sem digitar, liberando o dispositivo de áudio; a retomada leva cerca de 6 ms.

## 0.11.1

- Corrige a rolagem com dois dedos no touchpad (e a roda do mouse) quando os efeitos visuais estão ligados, como no perfil Retro Hacker. A camada de efeitos ficava numa janela sobreposta que, no X11, capturava os eventos de rolagem mesmo com repasse ativado.
- Os efeitos agora são desenhados diretamente sobre o terminal, sem nenhuma janela intermediária para cliques, toques ou rolagem.
- Teste gráfico de regressão com evento real do X (via `xdotool`) e efeitos ligados.

## 0.11.0

- Perfis personalizados: salve as configurações atuais como perfil em **Preferências → Geral** ou pela paleta de comandos.
- Cada perfil guarda tema, fonte, tamanho, shell, cursor, opacidade, efeitos, painel e diretório inicial.
- Perfis podem ter ações rápidas próprias, iniciadas como cópia da lista em uso e trocadas automaticamente junto com o perfil.
- Editar, atualizar com as configurações atuais e remover perfis personalizados; os perfis internos continuam protegidos.
- Perfis ficam em `~/.config/hacker-terminal/profiles/`; arquivos inválidos ou que tentem substituir um perfil interno são ignorados com aviso.
- Diretório inicial inexistente em um perfil volta para a pasta pessoal em vez de impedir a abertura.
- Nomes com acentos geram identificadores legíveis (`Laboratório` → `laboratorio`), também para temas.
- `--list-profiles` indica a origem de cada perfil; `--diagnose` mostra o perfil ativo e arquivos de perfil ignorados.

## 0.10.0

### Personalização
- Atalhos de teclado editáveis em **Preferências → Atalhos**, com gravação por tecla, detecção de conflitos, restauração individual ou total e seção `[shortcuts]` no `config.ini`.
- Editor visual de temas: crie, duplique, edite e remova temas personalizados com seletores de cor para a interface, o terminal e as 16 cores ANSI.
- Formato e piscar do cursor, negrito com cores claras, copiar ao selecionar e rolagem ao receber saída ou ao digitar.
- Opacidade do fundo (30–100%) quando há um compositor de janelas ativo.
- Shell personalizado com argumentos; se ele falhar, o terminal volta automaticamente ao shell de login.
- Preferências reorganizadas nas abas Geral, Aparência, Terminal e Atalhos.
- `Ctrl` + roda do mouse ou do touchpad altera o tamanho da fonte.
- Novo atalho `Ctrl+Shift+O` para alternar entre painéis divididos e `Ctrl+,` para abrir as Preferências.
- Dicas do cabeçalho mostram os atalhos realmente configurados.

### Robustez
- Corrige a perda de todas as preferências quando um valor continha `%`; a gravação também falhava sem tratamento.
- Seções desconhecidas do `config.ini` são preservadas ao salvar, e a gravação usa `fsync` antes da troca atômica.
- Confirmação antes de colar texto com várias linhas ou caracteres de controle ocultos; a colagem respeita o modo *bracketed paste*.
- Bell em abas de fundo marca a aba e pede atenção à janela.
- A sessão é salva automaticamente a cada 30 s, preservando o layout mesmo após falhas ou encerramento forçado.
- Log rotativo e privado em `~/.local/state/hacker-terminal/`, com registro de exceções não tratadas; `--debug` mostra detalhes no terminal.
- `--list-shortcuts` lista os atalhos em uso; `--diagnose` informa atalhos inválidos ou em conflito e o caminho do log.
- Cancelamentos de inicialização ao fechar abas não são mais tratados como erro.

## 0.9.0

- Corrige o diálogo de Preferências, que exibia apenas a primeira linha porque a área rolável não expandia; o mesmo ajuste vale para os editores de ações e a paleta.
- Corrige o layout em janelas estreitas: o painel lateral chegava a ocupar quase toda a largura e deixava o terminal com poucas colunas.
- Oculta o painel lateral automaticamente abaixo de 760 px; `Ctrl+Shift+B` o exibe temporariamente sem alterar a preferência salva.
- Reduz o tamanho mínimo da janela de 720×440 para 480×320.
- Substitui a barra superior por uma barra de status inferior com tema ativo, diretório atual, branch Git e ambiente virtual.
- Cabeçalho com ícones simbólicos, título da sessão ativa como subtítulo e título da janela dinâmico.
- Abas arredondadas com indicador do tema; a faixa de abas só aparece com mais de uma sessão.
- Painéis divididos ganham divisor fino e o painel inativo fica esmaecido.
- Visual revisado para painel lateral, pesquisa, menus, dicas, diálogos, interruptores e tela de abertura com barra de progresso.
- Preferências organizadas em seções e botões de confirmação destacados.
- Usa a variante escura do tema GTK para diálogos e seletores de arquivo.
- `Ctrl+=` também aumenta a fonte, cobrindo teclados em que `+` exige `Shift`.
- O timer dos efeitos visuais para quando os efeitos estão desligados.

## 0.8.4

- Substitui a interceptação manual de gestos pela integração nativa VTE/GTK recomendada para touchpads.
- Usa unidades em pixels e fallback de rolagem do VTE para deltas de alta resolução do XInput/libinput.
- Recupera o foco do terminal quando o XFCE/X11 consome o primeiro tap para ativar a janela.
- Mantém o campo de pesquisa focado ao reativar uma janela durante uma pesquisa.
- Corrige o limite de restauração para no máximo 20 painéis também durante a gravação.
- Amplia os testes gráficos de propriedades do VTE e do ciclo de ativação da janela.

## 0.8.3

- Adiciona suporte explícito a eventos nativos de toque e taps sintetizados pelo trackpad.
- Recupera o foco quando o gesto chega ao contêiner de rolagem em vez do VTE.
- Faz a rolagem suave do trackpad também reativar o terminal.
- Amplia o teste gráfico para toque, máscara de eventos e foco durante a rolagem.

## 0.8.2

- Faz o terminal recuperar o foco ao receber um clique após o uso da barra ou do painel lateral.
- Sincroniza o painel ativo quando o foco retorna ao VTE.
- Adiciona teste gráfico de regressão para alternância de foco por clique.

## 0.8.1

- Adiciona rolagem suave por gestos verticais do trackpad no histórico do terminal.
- Mantém roda convencional, gestos horizontais e combinações com `Ctrl`/`Alt` sob controle do VTE.
- Corrige a detecção de processos-filhos usada ao confirmar o fechamento de tarefas ativas.
- Testa deltas fracionários, limites do histórico, integração GTK/VTE e processos em execução.

## 0.8.0

- Adiciona divisão horizontal e vertical com foco e fechamento independentes.
- Restaura a orientação e os diretórios dos painéis divididos na sessão seguinte.
- Reconhece links seguros e permite abri-los com `Ctrl+clique` ou menu contextual.
- Exibe branch Git e ambiente virtual no status sem executar processos externos.
- Torna o diálogo de preferências redimensionável e rolável.
- Testa divisões, restauração de layout, links e contexto de projeto.

## 0.7.0

- Torna Minimal Dark, sem boot, efeitos ou sons, o padrão profissional para novas configurações.
- Adiciona perfis Desenvolvimento, Foco e Retro Hacker, disponíveis também pela CLI.
- Faz novas abas herdarem o diretório real da sessão ativa.
- Torna as ações laterais criáveis, editáveis, ordenáveis e removíveis, com confirmação opcional.
- Restaura com segurança tamanho da janela, diretórios, abas e aba ativa da sessão anterior.
- Adiciona paleta pesquisável para comandos, ações, perfis e temas em `Ctrl+Shift+P`.
- Amplia os testes unitários e gráficos para cobrir cada etapa da evolução profissional.

## 0.6.1

- Restaura as oito ações rápidas do painel lateral dentro de uma área com rolagem própria.
- Adapta largura, espaçamento e tamanho mínimo para janelas pequenas e telas compactas.
- Adiciona `Ctrl+Shift+B` para mostrar ou ocultar o painel de ações.
- Amplia o smoke test gráfico para detectar ações ausentes e regressões responsivas.

## 0.6.0

- Adiciona cinco temas internos: Matrix Green, Cyberpunk Purple, Amber CRT, Ice Blue e Minimal Dark.
- Aplica temas imediatamente à interface GTK, terminal, paleta ANSI, cursor, seleção e efeitos.
- Adiciona importação, exportação, validação e fallback seguro para temas personalizados em INI.
- Persiste o tema selecionado e adiciona `--theme` e `--list-themes` à linha de comando.
- Amplia os testes unitários, gráficos, de instalação e do pacote Debian para cobrir temas.

## 0.5.0

- Adiciona sessões em abas com criação, navegação, títulos dinâmicos e fechamento seguro.
- Adiciona pesquisa literal no histórico de cada terminal, com navegação anterior/próxima.
- Persiste fonte, tamanho, scrollback, boot, efeitos, som e painel lateral em configuração privada.
- Adiciona diálogo de preferências e painel lateral recolhível.
- Reorganiza o aplicativo em módulos testáveis, mantendo um executável compatível.
- Adiciona testes unitários e smoke test gráfico para abas, busca e persistência.

## 0.4.0

- Corrige o ciclo de vida do shell, fechamento da janela e cancelamento de inicialização.
- Sincroniza tela cheia com o estado real do gerenciador de janelas.
- Encerra corretamente o timer dos efeitos e torna a geração de áudio atômica e segura.
- Reduz o custo da detecção de Nerd Fonts, evitando varrer todas as fontes no caminho comum.
- Corrige instalação em caminhos contendo espaços e integra o ícone à janela e ao menu.
- Adiciona novo ícone vetorial hacker, metadados AppStream e pacote Debian reproduzível.
- Amplia os testes para ícone, metadados, instalação e conteúdo do pacote `.deb`.

## 0.3.1

- Adiciona rolagem vertical nativa ao histórico do VTE.
- Simplifica o painel de ações com botões compactos, menos bordas e hierarquia visual mais discreta.

## 0.3.0

- Detecta Nerd Fonts e valida a cobertura real de glifos Powerline.
- Adiciona diagnóstico, escolha de fonte, tamanho e controles de acessibilidade pela CLI.
- Adiciona zoom, tela cheia e menu de contexto.
- Torna o instalador independente do diretório atual e reversível.
- Adiciona ícone próprio, desktop entry validável, smoke tests e documentação comunitária.

## 0.2.2

- Versão GTK/VTE inicial com painel defensivo, boot e efeitos audiovisuais.
