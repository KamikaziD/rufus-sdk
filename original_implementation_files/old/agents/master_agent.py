from old.agents.ocr_agent import OCRAgent
from old.agents.info_agent import InfoAgent
from old.agents.rag_agent import RAGAgent
from old.models.agent import ExecutionPlan, PlanStep, ExecutionMode
from typing import Dict, Any, Optional, Callable, Awaitable
import asyncio
import time
import json
from datetime import datetime
from old.services.redis_service import redis_service


class MasterAgent:
    def __init__(
        self,
        agent_models: Dict[str, str],
        system_prompts: Dict[str, str],
        client_id: Optional[str] = None,
        is_cancelled: Optional[Callable[[], Awaitable[bool]]] = None,
    ):
        self.ocr_agent = OCRAgent(
            agent_models["ocr"], system_prompts["ocr"], client_id=client_id, is_cancelled=is_cancelled)
        self.info_agent = InfoAgent(
            agent_models["info"], system_prompts["info"], client_id=client_id, is_cancelled=is_cancelled)
        self.rag_agent = RAGAgent(
            agent_models["rag"],
            agent_models["embedding"],
            system_prompts["rag"],
            client_id=client_id,
            is_cancelled=is_cancelled,
        )
        self.agent_models = agent_models
        self.client_id = client_id
        self.is_cancelled = is_cancelled

    def analyze_request(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Analyze user request to determine required agents"""
        query_lower = query.lower()
        context_text = context.get("text", "").lower() if context else ""
        urls_present = bool(context.get("urls")) if context else False

        needs_ocr = "compliance" in context_text or any(
            kw in query_lower for kw in ["compliance", "document", "text", "extract", "read", "scan"]) or urls_present
        needs_info = any(kw in query_lower for kw in [
                         "search", "find", "information", "lookup", "research"])
        needs_rag = True  # Always use RAG for context

        complexity = sum([needs_ocr, needs_info, needs_rag])

        return {
            "needs_ocr": needs_ocr,
            "needs_info": needs_info,
            "needs_rag": needs_rag,
            "complexity": complexity,
            "summary": f"Request requires {complexity} agents. OCR: {needs_ocr}, Info: {needs_info}, RAG: {needs_rag}",
            "urls_present": urls_present
        }

    def create_execution_plan(self, analysis: Dict[str, Any]) -> ExecutionPlan:
        """Create execution plan based on analysis"""
        steps = []
        agents = []

        if analysis["needs_ocr"]:
            reason = "User request mentions document or text extraction."
            if analysis.get("urls_present"):
                reason = "URLs detected in the request, requiring content extraction."
            steps.append(PlanStep(
                id=len(steps) + 1,
                agent="OCR Agent",
                action="Extract and analyze text from document or URL",
                depends_on=[],
                reasoning=reason
            ))
            agents.append("OCR Agent")

        if analysis["needs_info"]:
            steps.append(PlanStep(
                id=len(steps) + 1,
                agent="Info Agent",
                action="Search for relevant information",
                depends_on=[],
                reasoning="User request requires external information lookup."
            ))
            agents.append("Info Agent")

        if analysis["needs_rag"]:
            depends_on = [1] if analysis["needs_ocr"] else []
            steps.append(PlanStep(
                id=len(steps) + 1,
                agent="RAG Agent",
                action="Query knowledge base for context",
                depends_on=depends_on,
                reasoning="Knowledge base consultation needed for comprehensive response."
            ))
            agents.append("RAG Agent")

        return ExecutionPlan(
            steps=steps,
            agents=list(set(agents)),
            execution_mode=ExecutionMode.PARALLEL if analysis[
                "complexity"] > 1 else ExecutionMode.SEQUENTIAL,
            estimated_time=len(steps) * 1000
        )

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute the plan"""
        if self.is_cancelled and await self.is_cancelled():
            raise Exception("Task revoked")
        results = {}

        # Separate independent and dependent agents
        independent_steps = [s for s in plan.steps if not s.depends_on]
        dependent_steps = [s for s in plan.steps if s.depends_on]

        # Execute independent agents in parallel
        if plan.execution_mode == ExecutionMode.PARALLEL and len(independent_steps) > 1:
            tasks = []
            for step in independent_steps:
                await self.report_activity(
                    f"Starting parallel execution for {step.agent}: {step.action}")
                if step.agent == "OCR Agent":
                    tasks.append(
                        ("OCR Agent", self.ocr_agent.execute(query, context)))
                elif step.agent == "Info Agent":
                    tasks.append(
                        ("Info Agent", self.info_agent.execute(query, context)))

            parallel_results = await asyncio.gather(*[task[1] for task in tasks])
            for (agent_name, _), result in zip(tasks, parallel_results):
                results[agent_name] = result
                await self.report_activity(
                    f"Completed parallel execution for {agent_name}.")
        else:
            # Sequential execution
            for step in independent_steps:
                if self.is_cancelled and await self.is_cancelled():
                    raise Exception("Task revoked")
                await self.report_activity(
                    f"Starting sequential execution for {step.agent}: {step.action}")
                if step.agent == "OCR Agent":
                    results["OCR Agent"] = await self.ocr_agent.execute(query, context)
                elif step.agent == "Info Agent":
                    results["Info Agent"] = await self.info_agent.execute(query, context)
                await self.report_activity(
                    f"Completed sequential execution for {step.agent}.")

        # Execute dependent agents
        for step in dependent_steps:
            if self.is_cancelled and await self.is_cancelled():
                raise Exception("Task revoked")
            await self.report_activity(
                f"Starting dependent execution for {step.agent}: {step.action}")
            if step.agent == "RAG Agent":
                rag_context = context or {}
                if "OCR Agent" in results:
                    rag_context["text"] = results["OCR Agent"]["text"]
                results["RAG Agent"] = await self.rag_agent.execute(query, rag_context)
            await self.report_activity(
                f"Completed dependent execution for {step.agent}.")

        return results

    async def synthesize_results(
        self,
        results: Dict[str, Any],
        plan: ExecutionPlan,
        query: str
    ) -> str:
        """Synthesize results from all agents"""
        await self.report_activity("Synthesizing results from all agents.")
        output = "=== MASTER AGENT SYNTHESIS ===\n\n"
        output += f"📋 EXECUTION SUMMARY:\n"
        output += f"- Master Model: {self.agent_models['master']}\n"
        output += f"- Total Steps: {len(plan.steps)}\n"
        output += f"- Agents Used: {', '.join(plan.agents)}\n"
        output += f"- Execution Mode: {plan.execution_mode.value}\n\n"

        if "OCR Agent" in results:
            ocr = results["OCR Agent"]
            output += f"📄 OCR AGENT RESULTS:\n"
            output += f"- Model: {ocr['model']}\n"
            output += f"- Document Type: {ocr['detected_type']}\n"
            output += f"- Confidence: {ocr['confidence']*100:.0f}%\n"
            output += f"- Analysis:\n{ocr['analysis']}\n\n"

        if "Info Agent" in results:
            info = results["Info Agent"]
            output += f"🔍 INFO AGENT RESULTS:\n"
            output += f"- Model: {info['model']}\n"
            output += f"{info['full_response']}\n\n"

        if "RAG Agent" in results:
            rag = results["RAG Agent"]
            output += f"📚 RAG AGENT RESULTS:\n"
            output += f"- Model: {rag['model']}\n"
            output += f"- Embedding Model: {rag['embedding_model']}\n"
            output += f"- Vector Search Results: {rag['vector_results_count']}\n"
            output += f"- Collections Searched: {', '.join(rag['collections_searched'])}\n"
            output += f"\nResponse:\n{rag['response']}\n\n"

        output += f"💡 CONCLUSION:\n"
        output += f"All {len(plan.steps)} planned steps completed successfully.\n"

        await self.report_activity("Synthesis complete.")
        return output

    async def execute(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Main execution method"""
        start_time = time.time()

        if self.is_cancelled and await self.is_cancelled():
            raise Exception("Task revoked")

        await self.report_activity("Analyzing request...")
        # Analyze request
        analysis = self.analyze_request(query, context)
        await self.report_activity("Request analysis complete.")

        if self.is_cancelled and await self.is_cancelled():
            raise Exception("Task revoked")

        await self.report_activity("Creating execution plan...")
        # Create execution plan
        plan = self.create_execution_plan(analysis)
        await self.report_activity("Execution plan created.")

        if self.is_cancelled and await self.is_cancelled():
            raise Exception("Task revoked")

        await self.report_activity("Executing plan...")
        # Execute plan
        results = await self.execute_plan(plan, query, context)
        await self.report_activity("Plan execution complete.")

        if self.is_cancelled and await self.is_cancelled():
            raise Exception("Task revoked")

        # Synthesize results
        final_result = await self.synthesize_results(results, plan, query)

        duration = time.time() - start_time

        return {
            "query": query,
            "analysis": analysis,
            "plan": plan.dict(),
            "results": results,
            "final_result": final_result,
            "duration": duration,
            "status": "success"
        }

    # Add report_activity method to MasterAgent as well, inheriting from BaseAgent
    async def report_activity(self, message: str, is_error: bool = False):
        """Report master agent activity to the client via Redis Pub/Sub"""
        if self.client_id:
            activity_message = {
                "type": "activity_update",
                "agent": "Master Agent",  # Master agent specific
                "message": message,
                "is_error": is_error,
                "timestamp": datetime.now().isoformat()
            }
            await redis_service.publish(
                f"agent_results:{self.client_id}", json.dumps(activity_message))
