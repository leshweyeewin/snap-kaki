# Why SnapKaki exists

My mother struggles with her phone. Where things are, what a gesture does,
why the screen changed. The difficulty is the machine.

My father could not work out how to log out of his email. Later, an
employment onboarding form asked him for details he had no way to interpret.
He can read. He can tap. What defeated him was not the phone — it was that
nothing on the screen explained what it was actually asking for, or what
would happen if he got it wrong.

Last month a visa form defeated me. I am a senior engineer with a Master's
in AI. Not because I could not use a computer; because the form was opaque
and the cost of getting it wrong was real.

For a long time I read these as one problem with one name: *they are not
good with technology.* That reading is wrong, and it is wrong in a way that
matters, because it points at a solution that does not work.

My mother's problem is digital literacy — the device is unfamiliar, and the
fix is teaching, practice and better interface design. My father's
onboarding form and my visa form are **the same problem as each other**, and
it is a different one. Neither of us was blocked by the machine. We were
blocked by a document that would not explain itself, in a situation where
being wrong had a cost we could not see the size of. Strip away the age gap,
the language gap and the thirty years of computing experience between us,
and my father and I failed at the same wall.

> Confusing forms are not an elderly problem. They are a comprehension
> problem under consequence — and they stop a retiree and a senior engineer
> in exactly the same way.

The elderly are the sharpest and most sympathetic case. They are not the
market. The market is anyone holding a form they do not fully understand and
cannot afford to get wrong.

So we built for the second problem and not the first, and the reason is
honest rather than strategic: an AI assistant is a poor teacher of a device
it cannot see you holding, and a good explainer of a document you can show
it. Point a camera at a form and the whole problem is in frame. "Help my
mother learn her phone" is not a tractable thing to be useful about, and
pretending otherwise would produce a demo rather than a product.

## Why the existing answers don't close it

Every one of these exists and is used. The two that matter most are the
family member and the chatbot.

**Asking a family member** is the real incumbent, and it mostly works. It
fails in three ways: they are at work when you are at the form; asking
repeatedly costs something, because my father does not like needing help
with a logout button and that reluctance is itself a reason forms go
unfiled; and often the family member does not know either — I did not know
what my own visa form was asking. SnapKaki does not try to replace this. It
routes *to* it, at the moment it is actually warranted, with a written
summary of where things stand. The hand-off is a feature, not a fallback.

**A general-purpose chatbot** is the closest competitor and the clearest
contrast. Paste the question into any capable assistant and you get a fluent
answer. But it will answer confidently from the wrong revision — the
published CHAS form changed between Jan 2023 and Dec 2025, and a model
answering from training data describes a form that no longer exists in
exactly the same register as a correct answer. It has no stopping behaviour:
ask it to walk you through a legal declaration and it will. And you have to
know what to ask, which assumes you already identified what you did not
understand — whereas pointing a camera does not.

> A general assistant optimises for answering. SnapKaki optimises for
> knowing when not to.

The rest solve adjacent problems, and it is worth being precise about which:

| | Solves | Leaves untouched |
|---|---|---|
| Helplines and service counters | Authoritative answers, free | Queues, opening hours, and you must already know you need help |
| Google Translate, camera translation | The **language** gap | The **comprehension** gap. "Rental Status of Residence" in flawless Mandarin is just as unhelpful — the hard part is that a flat you are still paying a housing loan on counts as *Not Rented*, and no dictionary contains that |
| Autofill, prefilled government services | Data entry, for people who **already understand** the form | Comprehension — and arguably makes it worse, since you end up having submitted something you never read |
| Screen readers, zoom, high contrast | **Perception** — making out what is on the page | Everything after you have read every word perfectly |

Singapore's own prefill services are genuinely excellent and remove most of
the typing. They do not explain the declaration, and the hardcopy path this
demo uses exists precisely for the people who cannot use them.

## What the form itself admits

The strongest argument that this need is real is printed on the form.

Section 3 of the CHAS application has a line for an **interpreter**: name,
identification number and contact number of the person who read and
explained the form to a signatory who does not read English. The government
already knows these documents cannot be completed unaided by everyone who
needs them, and has built a human assist layer into the paper itself.

SnapKaki is the always-on version of that line — with one honest difference,
and it is the one that defines the product. A human interpreter can witness
a signature. Software cannot. So at the signature, SnapKaki stops and asks
for a person.
