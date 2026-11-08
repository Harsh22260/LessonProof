# Introduction to Retrieval-Augmented Generation

## Welcome to AI and RAG

Imagine you are in a school library in India, trying to find a rule book. You need a helpful helper to look up facts before you write your answers. Retrieval-Augmented Generation, or RAG, is like having an open-book exam where you can look up facts from outside notes. Artificial intelligence, or AI, means computer systems that do tasks which normally need human thinking. An AI model is a computer program that has learned patterns from many examples, just like how you learn grammar rules by reading many sentences.

## What RAG Means

RAG stands for Retrieval-Augmented Generation. Think of it like looking up an answer in your textbook before speaking, instead of only guessing from memory. The term was introduced in a 2020 research paper by Patrick Lewis and colleagues. A large language model, or LLM, is an AI model trained on very large amounts of text. It generates text by predicting likely next words.

A prompt is the text given to an LLM, which can include instructions and background text.

## Why We Need RAG

Think of an LLM like a student who has read many books before an exam. It knows a lot, but it has not read your school's new circulars issued today. An LLM alone answers only from what it learned during its training. It does not know about events after its training data ends. It also does not know your private company documents unless you give them to it.

LLMs can sometimes produce text that sounds very confident but is completely false. This problem is called hallucination. RAG brings outside facts so you get better answers without needing to retrain the model. Because the answer is based on retrieved text, a RAG system can show which documents it used, so people can check the answer.

## How RAG Works Step by Step

Before questions can be answered, documents go through a preparation step called indexing. Think of it like sorting your school study notes into labeled folders before an exam. Documents are split into small pieces called chunks because models can only take limited text. Think of it like cutting a long story into small sentence strips so you can read them easily. An embedding is a list of numbers that represents the meaning of text.

Think of it like a set of test scores that shows how close two subjects are to each other, where similar topics get close scores. An embedding model is an AI model that turns text into these meaning numbers. A vector database is a system that stores these numbers and quickly finds the closest ones. Think of it like a smart library shelf that groups similar books right next to each other so you can find them fast. At question time, retrieval finds relevant text, augmentation adds it to the prompt, and generation writes the final answer.

## RAG in Action

Let us follow a simple question about school library rules. A user asks this question: 
> What is the fine for a late book?

The system searches the index and finds this text chunk:
> Fines for returning a library book late are five rupees per day.

The system builds this exact prompt for the model:
> Here is the rule: Fines for returning a library book late are five rupees per day. Question: What is the fine for a late book? Answer it using the text.

The LLM reads the prompt and generates this final answer:
> The fine for returning a library book late is five rupees per day.

## Limits of RAG

RAG can reduce wrong answers, but it does not remove them completely. The LLM can still make mistakes even when it is given the right text. RAG can fail if the needed information is missing from your documents. It can also fail if retrieval misses the right chunk or the model fails to use it. The quality of your final answer depends heavily on your documents and your retrieval step.

## Summary and Self-Check

You have learned that RAG brings outside knowledge together with a language model. You saw how documents are split into chunks and turned into embeddings for easy search. You also learned about retrieval, augmentation, and generation steps. Now test what you know with the questions below.

## Key Words

- **AI model**: A computer program that has learned patterns from a lot of examples.
- **Large language model (LLM)**: An AI model trained on very large amounts of text that generates text by predicting next words.
- **Prompt**: The text given to an LLM, which can include instructions, background text, and a question.
- **Hallucination**: When an LLM produces text that sounds confident but is false or made up.
- **RAG (Retrieval-Augmented Generation)**: A method that adds an outside source of knowledge to help an LLM base its answer on facts.
- **Chunk**: A small piece of a document made during the indexing stage.
- **Embedding**: A list of numbers that represents the meaning of a piece of text.
- **Embedding model**: An AI model that turns text into embeddings.
- **Vector database**: A system that stores embeddings and quickly finds the ones closest to a question.
- **Retrieval**: The question-time step that finds relevant text in outside sources.
- **indexing**: The step that prepares documents so they can be searched.
- **augmentation**: The step that adds the retrieved text to the prompt.

## Check Yourself

**Question 1.** What do the letters RAG stand for?

*Answer:* RAG stands for Retrieval-Augmented Generation.

**Question 2.** Why does a RAG system split large documents into smaller chunks?

*Answer:* Because a model can only take in a limited amount of text at one time, and a small piece is easier to match to a specific question.

**Question 3.** Suppose a store updates its return policy document with new rules. How can you update a RAG system with these new rules without retraining the LLM?

*Answer:* You can update the documents and the index to include the new policy, so the retrieval step brings up the new rules in the prompt.
