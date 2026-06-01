# Сравнение с аналогами

## Главный тезис

Готовые модели и moderation API полезны как detector или guardrail-компоненты. GenSecOps AI Security Gateway решает дополнительную задачу: создаёт независимый банковский контур допуска артефакта с quarantine, policy decision, подписанным паспортом безопасности, verified download и audit.

## Сравнение

| Решение | Что делает | Сильная сторона | Ограничение | Почему нашего подхода недостаточно заменить им |
|---|---|---|---|---|
| ShieldGemma 2 | Open-weight модель Google на базе Gemma 3 4B для классификации безопасности синтетических и естественных изображений по заданной policy. | Можно использовать как входной или выходной image safety filter и развернуть в собственном контуре. | Это detector: качество требует отдельной валидации на банковских данных и таксономии. В model card заявлены ограниченные harm types и English-only setup обучения. | Модель можно подключить как output detector, но она сама не создаёт обязательный маршрут `quarantine → policy → signed passport → verified download → audit`. |
| UnsafeBench | Исследовательский benchmark для оценки эффективности и устойчивости image safety classifiers на реальных и AI-generated изображениях; работа также представляет PerspectiveVision. | Помогает измерять качество detector-слоя и учитывать distribution shift для AI-generated изображений. | Это benchmark и исследовательский baseline, а не готовый банковский release-контур. | Полезен для выбора и проверки detector, но не управляет выдачей артефакта пользователю. |
| Azure AI Content Safety | Облачные API Microsoft для анализа текста и изображений на harmful content; есть severity levels, prompt protection и custom categories. | Готовый managed-сервис с мультимодальной модерацией и инструментами настройки. | Это внешний сервис анализа контента. Банку всё равно нужен собственный контроль жизненного цикла артефакта, интеграция с policy и аудитом выдачи. | Можно использовать как detector-компонент, но независимый контур должен решать, когда артефакт допускается к release и скачиванию. |
| AWS Bedrock Guardrails | Настраиваемые guardrails для GenAI-приложений: content filters, prompt attacks, sensitive information filters и другие политики; может блокировать или маскировать контент в application flow. | Сильная интеграция с Bedrock и возможность применять политики к входам и ответам. | Это развитый guardrail-сервис, но не готовая реализация именно нашего bank-specific image artifact release flow с подписанным паспортом и проверкой целостности при скачивании. | Подходы дополняют друг друга: Bedrock Guardrails может быть одним из policy/detector-компонентов, а GenSecOps фиксирует независимый порядок допуска и выдачи артефакта. |
| OpenAI Moderation | API классификации потенциально harmful text и image inputs по категориям; `omni-moderation-latest` принимает изображения. | Быстро подключаемый managed moderation API с категориями и scores. | Это API классификации. Для изображений поддерживается не каждая категория, что отражено в документации. | API возвращает сигнал для решения, но не реализует quarantine, паспорт безопасности, release storage и verified download банка. |
| GenSecOps AI Security Gateway | Независимый enforcement-контур: входные проверки, quarantine результата, deterministic policy, fail closed, signed safety passport, release только после `ALLOW`, verified download и append-only audit. | Генератор считается недоверенным; detector можно заменить через adapter без изменения маршрута допуска. | Текущий MVP доказывает архитектуру и enforcement, но не production ML quality: detector и PII/OCR реализованы demo-адаптерами. | Не заменяет специализированные detector-модели. Оборачивает их в контролируемый банковский процесс выдачи. |

## Вывод для защиты

> Мы не конкурируем с detector-моделями и managed moderation API. Мы превращаем их сигналы в проверяемое банковское решение о допуске артефакта.

## Источники

- [Google AI for Developers: ShieldGemma 2 model card](https://ai.google.dev/gemma/docs/shieldgemma/model_card_2)
- [UnsafeBench paper](https://arxiv.org/abs/2405.03486)
- [Microsoft Learn: Azure AI Content Safety overview](https://learn.microsoft.com/en-us/azure/ai-services/content-safety/overview)
- [AWS Documentation: Amazon Bedrock Guardrails components](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-components.html)
- [OpenAI API: Moderation guide](https://platform.openai.com/docs/guides/moderation/)

