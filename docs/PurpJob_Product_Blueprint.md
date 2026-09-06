# PurpJob — источник истины по продукту

Это **постоянная ссылка**. Всё в репозитории — README, комментарии в коде,
ссылки из FRD — указывает сюда, а не на файл с номером версии. Когда выходит
новая версия мастер-документа, меняется одна строка в этом файле, а не десятки
ссылок по всему репозиторию.

## Действующая версия

| | |
|---|---|
| Версия | **10.17** |
| Файл | [`history/PurpJob_Master_Document_10_17.md`](history/PurpJob_Master_Document_10_17.md) |
| Положен в репозиторий | 6 сентября 2026 |
| Расхождения с кодом | [`divergence-10.17.md`](divergence-10.17.md) |

> **Что изменилось при переходе с 10.16.** Файл 10.17 положен в репозиторий как
> есть, без правок и пересказа. Разница с кодом выписана отдельно — в
> [`divergence-10.17.md`](divergence-10.17.md), и там же сказано, почему ни
> один пункт не был реализован при сверке: новая версия мастер-документа
> меняет то, с чем сверяются, а не то, что построено.
>
> Теги **[MVP] / [V2] / [V3] / [Vision]** и границы этапов продукта остались
> прежними. Появление функции в 10.17 не переносит её в текущий этап само по
> себе.

Предыдущая версия — [`history/PurpJob_Master_Document_10_16.md`](history/PurpJob_Master_Document_10_16.md),
положена 4 сентября 2026. Версионированные документы не редактируются: чтобы
понять, что и когда решили, нужно видеть обе.

## Что считается источником истины

Порядок важен: при расхождении выигрывает то, что выше.

1. **Мастер-документ** — продуктовая стратегия, принципы, гипотезы, объём
   этапов.
2. **FRD модуля** — требования к конкретному модулю. FRD не может отменить
   принцип мастер-документа; там, где он с ним расходится, расхождение должно
   быть выписано явно.
3. **README** — что построено на самом деле, включая честные отступления от
   FRD и причины.
4. **Тесты** — исполняемая запись тех решений, которые легко потерять при
   доработке.

Код источником истины не является нигде. Если код расходится с чем-то из
списка — это дефект кода либо незаписанное решение, но не новая норма.

## Требования по модулям

| Модуль | Документ |
|---|---|
| 2 — Обогащение и доказательства | [`PurpJob_Module2_Enrichment_Evidence_FRD.md`](PurpJob_Module2_Enrichment_Evidence_FRD.md) |
| 3 — PROF.индекс | [`PurpJob_Module3_PROF_Index_FRD.md`](PurpJob_Module3_PROF_Index_FRD.md) |
| 4 — Contextual Probe | [`PurpJob_Module4_Contextual_Probe_FRD.md`](PurpJob_Module4_Contextual_Probe_FRD.md) |
| 5 — NDA и альтернативная верификация | [`PurpJob_Module5_NDA_Alternative_Verification_FRD.md`](PurpJob_Module5_NDA_Alternative_Verification_FRD.md) |
| 6 — Trust Score | [`PurpJob_Module6_Trust_Score_FRD.md`](PurpJob_Module6_Trust_Score_FRD.md) |
| 7 — Объяснимость и модерация | [`PurpJob_Module7_XAI_Moderation_FRD.md`](PurpJob_Module7_XAI_Moderation_FRD.md) |
| 8 — Накопительный профиль | [`PurpJob_Module8_Cumulative_Profile_FRD.md`](PurpJob_Module8_Cumulative_Profile_FRD.md) |
| 9 — Экспорт профиля | [`PurpJob_Module9_Profile_Export_FRD.md`](PurpJob_Module9_Profile_Export_FRD.md) |
| 10 — Вакансии и Match | [`PurpJob_Module10_Vacancies_Match_FRD.md`](PurpJob_Module10_Vacancies_Match_FRD.md) |
| 11 — Цикл возвращения | [`PurpJob_Module11_Candidate_Retention_Loop_FRD.md`](PurpJob_Module11_Candidate_Retention_Loop_FRD.md) |
| 12 — Рекрутерская сторона | [`PurpJob_Module12_Recruiter_Candidate_View_FRD.md`](PurpJob_Module12_Recruiter_Candidate_View_FRD.md) |
| 13 — Поэтапное раскрытие | [`PurpJob_Module13_Progressive_Reveal_FRD.md`](PurpJob_Module13_Progressive_Reveal_FRD.md) |
| 14 — Калибровка | [`PurpJob_Module14_Recruiter_Feedback_Calibration_FRD.md`](PurpJob_Module14_Recruiter_Feedback_Calibration_FRD.md) |
| 15 — Плагин рекрутера | [`PurpJob_Module15_Recruiter_Plugin_FRD.md`](PurpJob_Module15_Recruiter_Plugin_FRD.md) |
| 16 — Агрегация вакансий | [`PurpJob_Module16_Vacancy_Aggregation_Reverse_Matching_FRD.md`](PurpJob_Module16_Vacancy_Aggregation_Reverse_Matching_FRD.md) — чертёж, не реализуется |

Дорожная карта модулей: [`roadmap.md`](roadmap.md).

## Архив версий

Версионированные документы лежат в [`history/`](history/) и не редактируются.
Продуктовая стратегия правится в мастер-документе, а не здесь: этот файл —
указатель, а не пересказ.
