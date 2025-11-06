@router.api_route("/medulla/stream/{path:path}", methods=["POST", "GET"])
async def proxy_module_requests_streaming(
     request: Request,
     path: str,
     secret: str=Depends(verify_shared_secret)
):
      """
      Relay endpoint for streaming requests to medulla service with Server-Sent Events (SSE) support.
      
      This endpoint acts as a proxy that forwards requests to medulla and streams the response
      back to the client in real-time. The connection remains open until the upstream service
      completes streaming or sends an end signal.
      
      Request Flow:
          Frontend (APC) -> Relay Endpoint -> Medulla Service -> Streams Events -> Frontend
      
      Args:
          request: FastAPI Request object containing headers, method, and body
          path: Endpoint path on medulla service (e.g., "archimedes/invoke")
          secret: Shared secret for authentication (verified via dependency injection)
      
      Returns:
          StreamingResponse: SSE stream with media type "text/event-stream"
      
      Example:
          POST /medulla/stream/archimedes/invoke
          Body: JSON payload expected by the archimedes/invoke endpoint
      """
      service_name = GET_SERVICE_NAME(request)
      parsed_url = urlparse(f"/{path}")
      query_params = parse_qs(parsed_url.query)
      external_url = f"{SERVICE_INTERACTION_HELPER.get_service_url(service_name)}{parsed_url.path}"
      formatted_params = {k: v if len(v) > 1 else v[0] for k, v in query_params.items()}

      headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in ["host", "content-length"]
      }
      headers.update(SERVICE_INTERACTION_HELPER.get_service_header("medulla"))
      body = await request.body()

      ALYF_LOGGER.log("INFO", f"Starting streaming relay: {request.method} {external_url}")

      async def event_generator():
            """Async generator that streams response chunks from medulla service."""
            try:
                  async with httpx.AsyncClient(timeout=600.0) as client:
                        async with client.stream(
                              method=request.method,
                              url=external_url,
                              params=formatted_params,
                              headers=headers,
                              content=body
                        ) as response:
                              ALYF_LOGGER.log("INFO", f"Stream established: status={response.status_code}")
                              
                              if response.status_code != 200:
                                    error_content = await response.aread()
                                    error_text = error_content.decode('utf-8', errors='ignore')
                                    ALYF_LOGGER.log("ERROR", f"Stream failed: status={response.status_code}, detail={error_text}")
                                    yield f"data: {json.dumps({'error': f'Stream failed with status {response.status_code}', 'status_code': response.status_code, 'detail': error_text})}\n\n"
                                    return

                              async for chunk in response.aiter_bytes():
                                    if chunk:
                                          yield chunk

                              ALYF_LOGGER.log("INFO", f"Stream completed: {external_url}")

            except httpx.TimeoutException as e:
                  ALYF_LOGGER.log("ERROR", f"Stream timeout: {external_url}, error={repr(e)}")
                  yield f"data: {json.dumps({'error': 'Stream timeout', 'status_code': 504})}\n\n"
            except Exception as e:
                  ALYF_LOGGER.log("ERROR", f"Stream exception: {external_url}, error={repr(e)}")
                  yield f"data: {json.dumps({'error': str(e), 'status_code': 500})}\n\n"

      return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                  "Cache-Control": "no-cache",
                  "Connection": "keep-alive",
                  "X-Accel-Buffering": "no"
            }
      )
