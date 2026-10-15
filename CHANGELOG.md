# Changelog

Este projeto segue [Semantic Versioning](https://semver.org/).

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
