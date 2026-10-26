% Lists every `endpoints_user_input/1` of a KB as `USER_INPUT: <file>:<line>`
% and every intra procedural flow from one into an open redirect sink as
% `OPEN_REDIRECT: <file>:<line> -> <line>`. Run from the queryengine
% working directory ( it consults `api.pl` ) :
%
%     swipl servlet_user_input.pl -- <kb_path>

:- style_check(-singleton).
:- initialization(main, main).

% The other frameworks' sink clauses read facts a one-file java KB may lack.
:- dynamic kb_class_has_3rd_party_super/3.
:- dynamic kb_call_method_of_class/3.

main :-
    current_prolog_flag(argv, [KB | _]),
    consult(KB),
    working_directory(Dir, Dir),
    atom_concat(Dir, 'api.pl', Api),
    consult(Api),
    forall(distinct(UI, endpoints_user_input(UI)),
           ( site(UI, File, Line), format("USER_INPUT: ~w:~w~n", [File, Line]) )),
    forall(distinct(UI-Sink, ( endpoints_user_input(UI), sinks_open_redirect(Sink), dataflow_intra_path(UI, Sink, _) )),
           ( site(UI, File, From), site(Sink, _, To), format("OPEN_REDIRECT: ~w:~w -> ~w~n", [File, From, To]) )).

% `startloc_<L>_<C>_endloc_<L>_<C>_<encoded path>` -> basename, start line
site(Location, File, Line) :-
    atomic_list_concat(Fields, '_', Location),
    Fields = [startloc, LineAtom | _],
    atom_number(LineAtom, Line),
    atomic_list_concat(Parts, '_slash_', Location),
    last(Parts, Encoded),
    atomic_list_concat(Words, '_dot_', Encoded),
    atomic_list_concat(Words, '.', File).
