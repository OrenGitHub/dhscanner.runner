% Counts the distinct `sinks_sqli/1` calls of a KB, per receiver file, and
% fails below a floor. Run from the queryengine working directory ( it
% consults `predicates/api.pl` ) :
%
%     swipl sqli_sinks.pl -- <kb_path> <min_sinks>
%
% Discourse ( b81bee142d3 ) : 6 sqli sinks before runner #142 / #146, 1,158
% after them, 1,152 of which are Ruby : every `DB.<sql method>` call ( `DB` holds a
% `MiniSql::ActiveRecordPostgres::Connection` subclass instance, see
% predicates `sinks/db/ruby/mini_sql.pl` ).

:- style_check(-singleton).
:- initialization(main, main).

main :-
    current_prolog_flag(argv, [KB, MinAtom | _]),
    atom_number(MinAtom, Min),
    consult(KB),
    working_directory(Dir, Dir),
    atom_concat(Dir, 'predicates/api.pl', Api),
    consult(Api),
    aggregate_all(count, distinct(Call, sinks_sqli(Call)), N),
    format("SQLI_SINKS: ~w ( >= ~w )~n", [N, Min]),
    (   N >= Min
    ->  format("PASS: ~w sqli sinks~n", [N])
    ;   format("FAIL: ~w sqli sinks, expected >= ~w~n", [N, Min]), halt(1)
    ).
