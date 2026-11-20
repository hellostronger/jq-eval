const fs=require('fs'),http=require('http'),path=require('path')
const root=path.join(__dirname, 'dist')
const api='http://127.0.0.1:8000'
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon'}
http.createServer((req,res)=>{
  const u=decodeURIComponent(req.url.split('?')[0])
  if(u.startsWith('/api/')){
    const opts={method:req.method,headers:{...req.headers,host:'127.0.0.1:8000'}}
    const pr=http.request(api+u,opts,ar=>{res.writeHead(ar.statusCode,ar.headers);ar.pipe(res)})
    pr.on('error',e=>{res.writeHead(502);res.end('proxy error')})
    req.pipe(pr)
    return
  }
  let p=path.join(root,u)
  if(!fs.existsSync(p)||fs.statSync(p).isDirectory()){p=path.join(root,'index.html')}
  const ext=path.extname(p).toLowerCase()
  fs.readFile(p,(e,d)=>{
    if(e){res.writeHead(500);res.end('err');return}
    res.writeHead(200,{'Content-Type':types[ext]||'application/octet-stream'})
    res.end(d)
  })
}).listen(3000,'127.0.0.1',()=>console.log('frontend with API proxy ready'))
