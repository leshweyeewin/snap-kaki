# Why SnapKaki exists

## Three people, one family, three different walls

**My mother and her phone.** She struggles with the device itself. Where
things are, what a gesture does, why the screen changed. The difficulty is
the machine.

**My father and a logout button.** He could not work out how to log out of
his email. Later, an employment onboarding form asked him for details he
had no way to interpret. He can read. He can tap. What defeated him was not
the phone — it was that nothing on the screen explained what it was
actually asking for, or what would happen if he got it wrong.

**Me and a visa form.** I am a senior engineer with a Master's in AI. Last
month a visa form defeated me. Not because I could not use a computer.
Because the form was opaque and the cost of getting it wrong was real.

For a long time I read these as one problem with one name: *they are not
good with technology.* That reading is wrong, and it is wrong in a way that
matters, because it points at a solution that does not work.

## The two problems hiding in that story

My mother's problem is **digital literacy**. The device is unfamiliar. The
fix is teaching, practice, better interface design — and it is a real
problem, but it is not the one this product solves.

My father's onboarding form and my visa form are **the same problem as each
other**, and it is a different one. Neither of us was blocked by the
machine. We were blocked by a document that would not explain itself, in a
situation where being wrong had a cost we could not see the size of.

Strip away the age gap, the language gap and the thirty years of computing
experience between us, and my father and I failed at the same wall.

That is the reframe the whole product rests on:

> Confusing forms are not an elderly problem. They are a comprehension
> problem under consequence — and they stop a retiree and a senior engineer
> in exactly the same way.

The elderly are the sharpest and most sympathetic case. They are not the
market. The market is anyone holding a form they do not fully understand
and cannot afford to get wrong.

## Why we scoped to the second problem

We could have built something for my mother's problem. We deliberately did
not, and the reason is honest rather than strategic: an AI assistant is a
poor teacher of a device it cannot see you holding, and a good explainer of
a document you can show it.

Point a camera at a form and the entire problem is in frame. That is a
tractable thing to be useful about. "Help my mother learn her phone" is not,
and pretending otherwise would produce a demo rather than a product.

## Why the existing answers do not close it

Every one of these exists. Every one is used. None of them solves it.

### Ask a family member

This is the real incumbent, and it mostly works. It also has three failures.

They are at work when you are at the form. Asking repeatedly costs
something — my father does not like needing help with a logout button, and
that reluctance is itself a reason forms go unfiled. And frequently the
family member does not know either; I did not know what my own visa form
was asking.

**SnapKaki does not try to replace this.** It routes *to* it, at the moment
it is actually warranted, with a written summary of where things stand. The
hand-off is a feature, not a fallback.

### Government helplines and service counters

Genuinely good, and the guidance corpus points people at them by name. They
have queues, opening hours, and a language barrier of their own. Most
importantly, they require you to already know that you need help — which
assumes you noticed the thing you misunderstood.

### Google Translate and camera translation

This is the closest tool most people reach for, and it addresses a
different barrier.

Translation moves words across a **language** gap. It does nothing about a
**comprehension** gap. "Rental Status of Residence" rendered in flawless
Mandarin is exactly as unhelpful as the English, because the hard part was
never the vocabulary — it is that a flat you are still paying a housing loan
on counts as *Not Rented*, and no dictionary contains that.

### A general-purpose chatbot

The strongest competitor, and the clearest contrast. Paste the question into
any capable assistant and you will get a fluent answer. Four problems:

1. **It will answer confidently from the wrong revision.** We proved this
   on our own corpus. The published CHAS form changed between Jan 2023 and
   Dec 2025: dwelling type lost its room-count options, rental status was
   rephrased, and the declaration moved from Clause 11 to Section 2B. A
   model answering from training data answers about a form that no longer
   exists, in the same confident register as a correct answer.
2. **It has no stopping behaviour.** A general assistant is optimised to
   answer. Ask it to walk you through a legal declaration and it will.
   SnapKaki's entire value is that it refuses at exactly that point.
3. **You have to know what to ask.** Typing a question requires already
   having identified what you do not understand. Pointing a camera does not.
4. **You would paste your identification number into it.** Most people do.

The one-line difference: a general assistant optimises for answering.
SnapKaki optimises for knowing when not to.

### Autofill, browser form-fill, prefilled government services

These solve a real problem — data entry — for people who **already
understand the form**. For someone who does not, hiding the fields behind
automation makes comprehension worse, not better. You end up having
submitted something you never read.

Singapore's own prefill services are genuinely excellent and remove most of
the typing. They do not explain the declaration, and the hardcopy path this
demo uses exists precisely for the people who cannot use them.

### Accessibility tooling

Screen readers, text zoom and high-contrast modes solve **perception** —
can you make out what is on the page. Our problem begins after you have read
every word perfectly.

## What the form itself admits

The strongest argument that this need is real is printed on the form.

Section 3 of the CHAS application has a line for an **interpreter**: name,
identification number and contact number of the person who read and
explained the form to a signatory who does not read English.

The government already knows these documents cannot be completed unaided by
everyone who needs them, and has built a human assist layer into the paper
itself. SnapKaki is the always-on version of that line.

With one honest difference, and it is the one that defines the product: a
human interpreter can witness a signature. Software cannot. So at the
signature, SnapKaki stops and asks for a person.
