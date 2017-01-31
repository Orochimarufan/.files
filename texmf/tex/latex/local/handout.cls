
% ---- Identification -----

\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{handout}

% ---- Initial Code ----

\RequirePackage{xifthen}
\newcommand{\putifne}[2]{\ifthenelse{\equal{#1}{}}{}{#2}}


% Schrift & Sprache
\RequirePackage[utf8]{luainputenc}
\RequirePackage[T1]{fontenc} % T1-Fonts
\RequirePackage[ngerman]{babel} % Deutsche Sonderzeichen und Silbentrennung (neue Rechtschreibung)
\RequirePackage{marvosym} % diverse Symbole
\RequirePackage{wasysym} % diverse Symbole 
\RequirePackage{fancyhdr}
%\RequirePackage{lastpage}
\RequirePackage{color}
\RequirePackage{pifont} % einige Befehle brauchen pifont (Symbole)
\RequirePackage{setspace}
%\RequirePackage[style=authortitle-dw]{biblatex}
\usepackage[a4paper,bottom=15mm]{geometry} % für Seitenränder, 

\pagenumbering{arabic}

% ---- Execution of Options ----

\ProcessOptions \relax

% --- Package Loading ----

\LoadClass[11pt]{scrartcl}

% ---- Main Code ----

% --- Setup the Page Layout ---
	\setlength\textwidth{170mm}
	\setlength\textheight{220mm}
	\setlength\oddsidemargin{-5mm}
	\setlength\evensidemargin{0in}
	\setlength\topmargin{-0.25in}
	\setlength\parindent{0in}
	\setlength\parskip{0.5em}

% --- Define Some Useful Commands ---
	% Define the default values for these commands
	\newcommand{\@university}{}
	\newcommand{\@faculty}{}
	\newcommand{\@semester}{}
	\newcommand{\@dozent}{}
	\newcommand{\@referent}{}
	\newcommand{\@martno}{}
	\newcommand{\@seminar}{}
	\newcommand{\@blank}{}
	
	\newcommand{\@DateTitle}{Datum: }
	\newcommand{\@DozentEn}{DozentIn}
	\newcommand{\@ReferentEn}{ReferentIn}

	% change the values if the user sets these commands
	\newcommand{\university}[1]{\renewcommand{\@university}{#1}}
	\newcommand{\faculty}[1]{\renewcommand{\@faculty}{#1}}
	\newcommand{\semester}[1]{\renewcommand{\@semester}{#1}}
	\newcommand{\dozent}[1]{\renewcommand{\@dozent}{#1}}
	\newcommand{\referent}[1]{\renewcommand{\@referent}{#1}}
	\newcommand{\martno}[1]{\renewcommand{\@martno}{#1}}
	\newcommand{\seminar}[1]{\renewcommand{\@seminar}{#1}}
	\newcommand{\DozentEn}[1]{\renewcommand{\@DozentEn}{#1}}
	\newcommand{\ReferentEn}[1]{\renewcommand{\@ReferentEn}{#1}}
	%\newcommand{\SetLiteratur}[1]{\bibliography{#1}}
	
	%\newcommand{\makeliteratur}{
	%
	%	\singlespacing
	%	\nocite{*}
	%	\printbibliography
	%}
	
	% redefine the make title command
	\renewcommand\maketitle{
		\thispagestyle{handouttitle}
		\vspace*{-10mm}
		\begin{center}
		\huge{\@title} \\
		\putifne{\@subtitle}{\LARGE{\@subtitle} \\}
		\end{center}
		\onehalfspacing 
	}

	% Redefine the sectioning commands \section \subsection and \subsubsection
	\renewcommand\section{\@startsection
		{section}{2}{0mm}{0.1\baselineskip}{0.1\baselineskip}{\normalfont\large\textbf}
	}
	\renewcommand\subsection{\@startsection
		{subsection}{2}{0mm}{0.1\baselineskip}{0.1\baselineskip}{\normalfont\normalsize\textbf}
	}
	\renewcommand\subsubsection{\@startsection
		{subsubsection}{2}{0mm}{0.1\baselineskip}{0.1\baselineskip}{\normalfont\normalsize\textbf}
	}
	\newenvironment{noindlist}
	 {\begin{list}{\labelitemi}{\leftmargin=1em\itemindent=0em\topsep=-5em\itemsep=-4pt}}
	 {\end{list}}
	 

% --- Define the Header and Footer Styles ---

	% The style for the page with \maketitle called on it.
	\fancypagestyle{handouttitle} {
		\renewcommand\headrulewidth{0.5pt}
		\renewcommand\footrulewidth{0.5pt}
		\chead{}
		\cfoot{}
		\lhead{ \small
				\putifne{\@university}{\textbf{\@university}\\}
				\putifne{\@faculty}{\textit{\@faculty}\\}
				\putifne{\@seminar}{\@seminar\\}
				\putifne{\@dozent}{\@DozentEn : \@dozent}
			  }	
		\lfoot{}
		\rhead{\@blank \small
				\putifne{\@referent}{\@ReferentEn : \@referent\\}
				\putifne{\@martno}{Matrikelnummer: \@martno\\}
				\@DateTitle\@date
				\putifne{\@semester}{\\\@semester}
			  }
		\rfoot{\thepage}
		\addtolength{\headheight}{10mm}
	}

	% The style for pages without \maketitle called on it.
	\fancypagestyle{handout} {
		\renewcommand\headrulewidth{0.5pt}
		\renewcommand\footrulewidth{0.5pt}
		\chead{}
		\cfoot{}
		\rhead{ \@blank \textbf{\small \@title} \\  \small \textbf{\@date} }
		\rfoot{\thepage}
		\lhead{ \small \@seminar \\ \@semester\ }
		\lfoot{}
	}
	
% Set the default page style to handout.
	\pagestyle{handout}

% Load at last
\RequirePackage[babel, german=quotes]{csquotes}
\RequirePackage{longtable}
\RequirePackage{multirow}
\usepackage[
   % Farben fuer die Links
   colorlinks=true,         % Links erhalten Farben statt Kaeten
   urlcolor=black,    % \href{...}{...} external (URL)
   filecolor=black,  % \href{...} local file
   linkcolor=black,  % \ref{...} and \pageref{...}
   citecolor=black,
   menucolor=black,
   % Links
   raiselinks=true,			 % calculate real height of the link
   breaklinks,              % Links berstehen Zeilenumbruch
   verbose,
   hyperfootnotes=false,    % Keine Links auf Fussnoten
   % Anchors
   plainpages=false,        % Anchors even on plain pages ?
   pageanchor=true,         % Pages are linkable
   pdfstartview=FitH,       % Dokument wird Fit Width geoeffnet
]{hyperref}