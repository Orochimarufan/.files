" General
""""""""""""""""""""""""""""""""""""""""""""""""""""""""
set history=200 "hi

" Fast Saving
nmap <leader>w: :w!<cr>

" Plugins
""""""""""""""""""""""""""""""""""""""""""""""""""""""""
" Load vim-plug
if empty(glob("~/.local/share/nvim/site/autoload/plug.vim"))
    execute '!curl -fLo ~/.local/share/nvim/site/autoload/plug.vim --create-dirs https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim'
endif

call plug#begin('~/.local/share/nvim/plugged')

Plug 'vim-airline/vim-airline'

" Style
Plug 'exitface/synthwave.vim'

call plug#end()

" User interface
""""""""""""""""""""""""""""""""""""""""""""""""""""""""
set scrolloff=7 "so

" Wildmenu
set wildmenu
set wildignore=*.o,*~,*.pyc,*.pyo

" Ruler
set ruler "ru
set number "nu

" Cmd Bar
set cmdheight=2 "ch

set hidden

" Backspace
set backspace=eol,start,indent
set whichwrap+=<,>,h,l

" Search
set ignorecase "ic
set smartcase "sc

set lazyredraw "lz

" Brackets
set showmatch "sm
set matchtime=2 "mat

" Errors
set t_vb=
set timeoutlen=500 "tm

" Colors & Fonts
"""""""""""""""""""""""""""""""""""""""""""""""""
syntax enable

set background=dark "bg
colorscheme synthwave

if has('termguicolors')
    set termguicolors
else
    let g:synthwave_termcolors=256
endif

" Files
"""""""""""""""""""""""""""""""""""""""""""""""""
set fileformats=unix,dos,mac "ffs

set modeline

set nobackup
set noswapfile

" Text
"""""""""""""""""""""""""""""""""""""""""""""""""
" Tabs
set expandtab "et
set smarttab "sta
set shiftwidth=4 "sw
set tabstop=4 "ts

" Indents
set autoindent "ai
set smartindent "si
set wrap

" Line Break
set linebreak "lbr
set textwidth=500 "tw

" Buffers
""""""""""""""""""""""""""""""""""""""""""""""""""
set switchbuf=useopen,usetab,newtab
set showtabline=2

