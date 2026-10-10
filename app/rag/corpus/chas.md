# CHAS Application Form — field guidance corpus

Grounding corpus for the field-explainer agent. One `##` section per chunk.
Each chunk is retrieved and handed to the model as the ONLY source it may
explain from. If a question is not covered here, the explainer must say it
does not know rather than improvise — that refusal is what keeps the
broad-vision version of this product safe.

Source: CHAS application form, chas.sg, January 2023 revision (publicly
downloadable, no SingPass needed). Plain-language restatement, not legal advice.

## What CHAS is

CHAS is the Community Health Assist Scheme. It is a Singapore government
subsidy card. With it, you pay less at participating GP and dental clinics.
Applying does not cost money. Applying does not commit you to anything —
you are asking to be assessed, and you can stop at any point.

There are several tiers (Blue, Orange, Green, and the Merdeka/Pioneer
Generation cards). You do not pick your tier on this form. The tier you get
is worked out from household income and property details after you apply.

## Why there is no income question on this form

This form never asks you to write down your income. This surprises people,
and it is the single most common reason someone thinks they have missed a
page. You have not missed a page.

Income is not self-declared because the government already holds it. When you
sign the declaration, you consent to IRAS and the CPF Board disclosing your
income information to the agency assessing your application. They look it up.

Practical consequence: if someone asks you to type your salary into a CHAS
form, something is wrong. Stop and check you are on an official form.

## Identification type — which one to circle

The form asks you to circle one identification type. The options are:

- **Pink NRIC** — you are a Singapore Citizen. Pink card.
- **Blue NRIC** — you are a Singapore Permanent Resident (PR). Blue card.
- **Birth Certificate** — for a child who has not been issued an NRIC yet.
  In Singapore an NRIC is issued at age 15, so this is normally for an
  applicant under 15.
- **FIN** — Foreign Identification Number, on a work pass, long-term visit
  pass, or student pass. Not a citizen or PR.

How to decide: look at the physical card in your hand and match the colour.
The colour is the answer. Do not guess from how long you have lived here —
a long-time resident can still hold a blue card.

CHAS eligibility normally requires Singapore Citizenship, so most successful
applicants circle Pink NRIC. If you hold a blue NRIC or a FIN, you can still
submit, but check your eligibility before you spend time on the form.

## Identification number — where to copy it from

Write the number exactly as printed on the card you just circled, including
the letter at the start and the letter at the end. Capital letters. No
spaces, no dashes.

A Singapore NRIC is one letter, seven digits, one letter — for example the
shape S1234567D. The first letter relates to status and year of birth; the
last letter is a checksum, so a single wrong digit makes the whole number
invalid. This is the field most worth checking twice.

If you are using a birth certificate, copy the birth certificate number in
the same way.

## Dwelling type — what it means and why it is asked

Dwelling type means what kind of home you live in. You are picking from a
list such as: 1-room / 2-room HDB flat, 3-room HDB, 4-room HDB, 5-room or
executive HDB, private housing (condominium or apartment), or landed
property.

Why it is asked: dwelling type is used as a rough proxy for household means,
alongside income. A smaller flat generally points to a higher subsidy tier.
It is not a judgement about you — it is one of the inputs to the tier
calculation.

How to answer: describe the flat you actually live in now, not one you used
to own and not one you are about to move into. If you live in an HDB flat,
count the rooms the way HDB does — a "3-room" flat means two bedrooms plus
a living room. If you are unsure of the room count, it is printed on your
HDB lease or your utilities bill.

## Rental status — rented from HDB vs renting from a landlord

This field asks whether your home is **rented** or **owned**, and this is a
genuinely confusing one because "rented" has a specific meaning here.

- **Owned** — you or a family member bought the flat, including a flat still
  being paid off with a mortgage or HDB loan. A flat you are paying a housing
  loan on is OWNED, not rented. This catches people out.
- **Rented from HDB** — you rent directly from the Housing & Development
  Board under a public rental scheme.
- **Rented from the open market** — you rent from a private landlord, whether
  the flat itself is HDB or private.

Why it is asked: households in public rental housing are generally assessed
as having greater need, so this affects the tier.

If you genuinely do not know whether the flat is owned or rented, do not
guess. The answer is on the lease or tenancy agreement, and getting it wrong
is a declared inaccuracy on a form you are about to sign.

## Mobile number — and who it should belong to

A Singapore mobile number, eight digits, starting with 8 or 9.

Whose number: it should be a number where the applicant can actually be
reached about this application. If the applicant does not use a mobile phone,
it is normal and acceptable to give a family member's number — but tell that
family member, because they will receive messages about the application and
may be asked to confirm things.

This is a good field to hand to the person helping you rather than guessing.

## Family members living at the same address

The form asks you to list the family members who live at the same address as
the applicant.

Why it is asked: CHAS is assessed on **household** means, not just the
applicant's own. The people you list here determine whose income is counted
and how many people it is divided between. A larger household divides the
same income across more people, which usually points to a higher subsidy.

Who to include: the people who actually live at that address with you, whose
names would appear on the household record — spouse, children, parents,
siblings living there.

Who not to include: a child who has moved out and lives elsewhere, even
though they are family. The test is the address, not the relationship.

This field has real consequences and is easy to get wrong in both directions.
If the household is complicated — someone works overseas, someone is
temporarily elsewhere, a tenant lives in a spare room — that is a question
for the agency or a family member, not something to guess at.

## Clause 11 — the declaration and consent (STOP HERE)

This is the legally significant part of the form. It is not a formality and
it should never be signed by someone who has not understood it.

By signing you are declaring two separate things:

1. **That all the information you have given is true and correct.** If it is
   not, the declaration states that the application may be rejected and the
   card withdrawn. You are personally asserting the accuracy of every field
   above — including the dwelling type, the rental status, and the household
   list, which are exactly the fields people most often get wrong.

2. **That you consent to IRAS and the CPF Board disclosing your income
   information** to the assessing agency. This is the step that replaces a
   self-declared income field. You are authorising a government-to-government
   lookup of your financial records.

Why an assistant must stop here: this is a signature on a legal declaration
with a consequence for getting it wrong. No automated helper should complete
it on someone's behalf, and no one should sign it because software told them
to. The right move is to pause, re-read the fields being declared, and bring
in a family member or the agency before signing.

## The interpreter and witness section

The form has a separate section for cases where the person signing does not
read English. An interpreter signs to confirm that the form was read and
explained to the signatory in a language they understand, and that the
signatory appeared to understand it.

This is worth noticing: the government already accepts that these forms
cannot be completed unaided by everyone who needs them, and has built a
human assist layer into the paper itself. That section is the paper version
of what this product does — with the important difference that a human
interpreter can witness a signature and software cannot.

## Thumbprint instead of a signature

If the applicant cannot sign their name, the form allows a thumbprint in
place of a signature, normally witnessed. The same stop applies, more
strongly: an applicant who cannot sign is an applicant who should have a
trusted person present for the declaration.

## What to do when a field is genuinely unclear

The honest answer is sometimes "ask". For CHAS specifically: the scheme has a
public enquiry line and the clinics that participate can often help, and the
agency can confirm household and property details that you should not guess.

Guessing on a form you are about to sign a truth declaration over is the one
move that turns a slow afternoon into a withdrawn card.
